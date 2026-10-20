use std::{
    borrow::Cow,
    cell::RefCell,
    fs,
    path::{Path, PathBuf},
    process,
    sync::LazyLock,
    time::{Duration, Instant},
};

use crfsuite::{Attribute, Model, Tagger};

use regex::Regex;
use rustc_hash::FxHashSet;
use serde::Serialize;

use crate::{
    estado::ESTADOS,
    normalizar,
    separador_endereco::TipoToken::{Alpha, Desconhecido, Digito, Pontuacao},
    Endereco,
};

const MODEL_DOWNLOAD_PATH: &str =
    "https://github.com/ipea/enderecobr_rs/releases/download/modelo-crf-v0.1/tagger.crf";

/// Nome do arquivo do modelo dentro de um diretório informado pelo usuário ou
/// do diretório de cache do SO.
const MODELO_ARQUIVO: &str = "tagger.crf";

/// Diretório (arquivo ou diretório) onde o modelo deve ficar.
const VAR_AMBIENTE_MODELO: &str = "ENDERECOBR_MODELO_CRF";

/// Quando ativa (`1`, `true`, ...), proíbe o download: sem o modelo local a
/// função falha em vez de acessar a rede.
const VAR_AMBIENTE_SEM_DOWNLOAD: &str = "ENDERECOBR_MODELO_CRF_SEM_DOWNLOAD";

/// Vale para a requisição inteira (conexão + download dos ~1,1 MB), para que um
/// servidor que não responde não trave a inicialização da biblioteca.
const TIMEOUT_DOWNLOAD: Duration = Duration::from_secs(60);

fn is_pontuacao(word: &str) -> bool {
    word.chars().next().is_some_and(|c| PONTUACAO.contains(c))
}

// `&str` const: varrer ~30 bytes é bem mais barato no hot path do que um
// lookup em `FxHashSet<char>`, e não aloca nada na inicialização.
const PONTUACAO: &str = "!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~¨´°§¶·«»–—…“”‘’";

pub struct SeparadorEndereco {
    pub model: Model,
    pub extrator: ExtratorFeature,
}

pub struct ExtratorFeature {
    distancias_vizinhaca: Vec<i32>,
    regex_tokenizer: Regex,
}

#[derive(Serialize)]
pub struct SegmentoEndereco {
    pub valor: String,
    pub tipo: String,
}

#[derive(Serialize)]
pub struct EnderecoSegmentado {
    pub segmentos: Vec<SegmentoEndereco>,
}

#[derive(PartialEq)]
enum TipoToken {
    Pontuacao,
    Digito,
    Alpha,
    Desconhecido,
}

struct TokenInfo<'a> {
    normalizado: Cow<'a, str>,
    tam_bucket: u8,
    tipo: TipoToken,
    marcador_df: bool,
    marcador_palmas: bool,
    uf: bool,
}

impl ExtratorFeature {
    pub fn new(distancias_vizinhaca: Option<Vec<i32>>) -> Self {
        Self {
            distancias_vizinhaca: distancias_vizinhaca.unwrap_or(vec![-2, -1, 1, 2]),
            // \p{L} => caracteres unicode
            // \p{N} => números unicode
            // Parece que tinha diferença entre as implementações devido às regexes
            regex_tokenizer: Regex::new(r"\p{N}+|\p{L}+|[^\s\p{L}\p{N}]")
                .expect("regex do tokenizador é válida"),
        }
    }

    pub fn sent2features(&self, text: &str) -> Vec<Vec<String>> {
        let (toks, _) = self.tokenize(text);
        self.tokens2features(&toks)
    }

    pub fn tokens2features(&self, toks: &[&str]) -> Vec<Vec<String>> {
        let tok_info: Vec<TokenInfo> = toks.iter().map(|tok| self._token_info(tok)).collect();
        (0..toks.len())
            .map(|i| {
                let mut feats: Vec<String> = Vec::with_capacity(32);
                self._features_token(toks, &tok_info, i, &mut feats);
                feats
            })
            .collect()
    }

    /// Features de um token, já deduplicadas, escritas em `feats`.
    ///
    /// `feats` é limpo com [`Vec::clear`], que preserva a capacidade alocada,
    /// permitindo reutilizar o mesmo vetor entre tokens.
    fn _features_token(
        &self,
        sent: &[&str],
        tokens_info: &[TokenInfo],
        i: usize,
        feats: &mut Vec<String>,
    ) {
        feats.clear();
        self._features_posicao(sent, tokens_info, i, feats);
        feats.sort_unstable();
        feats.dedup();
    }

    /// Features de um token, já deduplicadas, convertidas em atributos do CRF.
    ///
    /// Internamente reutiliza o mesmo scratch `Vec<String>` entre os tokens:
    /// o vetor intermediário deixa de ser alocado uma vez por token.
    pub fn tokens2attributes(&self, tokens: &[&str]) -> Vec<Vec<Attribute>> {
        let tok_info: Vec<TokenInfo> = tokens.iter().map(|tok| self._token_info(tok)).collect();
        let mut atributos: Vec<Vec<Attribute>> = Vec::with_capacity(tokens.len());
        let mut feats: Vec<String> = Vec::with_capacity(32);
        for i in 0..tokens.len() {
            self._features_token(tokens, &tok_info, i, &mut feats);
            // `Attribute::from(String)` move a String; `Attribute::new(&str, 1.0)`
            // clonaria cada feature, dobrando as alocações por token. O `drain`
            // esvazia o scratch preservando sua capacidade.
            atributos.push(feats.drain(..).map(Attribute::from).collect());
        }
        atributos
    }

    fn _features_posicao(
        &self,
        sent: &[&str],
        tokens_info: &[TokenInfo],
        i: usize,
        feats: &mut Vec<String>,
    ) {
        feats.push("bias".to_string());
        feats.push(format!(
            "{}_pos",
            (i as f64 / sent.len() as f64 * 4.0) as i32
        ));

        let Some(tok_info) = tokens_info.get(i) else {
            return;
        };
        self._token_info_posicional(tok_info, 0, feats);

        if i == 0 {
            feats.push("BOS".to_string());
        }
        if i == sent.len().saturating_sub(1) {
            feats.push("EOS".to_string());
        }

        for &distancia in &self.distancias_vizinhaca {
            self._features_vizinhanca(sent, tokens_info, i, distancia, feats);
        }
    }

    fn _token_info<'a>(&self, token: &'a str) -> TokenInfo<'a> {
        let mut normalizado = normalizar(token);

        // O `all()` de um iterador vazio é `true`, então o token vazio precisa
        // ser tratado antes de tudo (espelha o `if len(token) == 0` do `preproc.py`).
        let tipo = if normalizado.is_empty() {
            Desconhecido
        } else if is_pontuacao(&normalizado) {
            Pontuacao
        } else if normalizado.bytes().all(|c| c.is_ascii_digit()) {
            Digito
        } else if normalizado.bytes().all(|c| c.is_ascii_alphabetic()) {
            Alpha
        } else {
            Desconhecido
        };

        let tam_bucket = if tipo == Digito {
            normalizado.trim_start_matches('0').len().min(10) as u8
        } else {
            normalizado.len().min(10) as u8
        };

        if tipo == Pontuacao {
            normalizado = Cow::Owned(normalizado.chars().take(1).collect());
        }

        // Empresta antes de mover: os campos de bool vêm primeiro,
        // `normalizado` (o move) vem por último. A ordem no literal importa.
        TokenInfo {
            marcador_df: MARCADORES_CONHECIDOS_DF.contains(normalizado.as_ref()),
            marcador_palmas: MARCADORES_CONHECIDOS_PALMAS.contains(normalizado.as_ref()),
            uf: SIGLAS_ESTADOS.contains(normalizado.as_ref()),
            normalizado,
            tam_bucket,
            tipo,
        }
    }

    /// Empilha as features de um token já com o prefixo posicional. Escreve
    /// direto no vetor da posição para não alocar um `Vec` por vizinho.
    fn _token_info_posicional(&self, tok_info: &TokenInfo, pos: i8, res: &mut Vec<String>) {
        res.push(format!("{}:{}", pos, tok_info.normalizado));
        res.push(format!("{}:tam:{}", pos, tok_info.tam_bucket));

        if tok_info.marcador_df {
            res.push(format!("{}:marcador_df", pos));
        }
        if tok_info.marcador_palmas {
            res.push(format!("{}:marcador_palmas", pos));
        }
        if tok_info.uf {
            res.push(format!("{}:sigla_estado", pos));
        }

        let tipo = match tok_info.tipo {
            Alpha => "is_alpha",
            Desconhecido => "is_unknown",
            Pontuacao => "is_punct",
            Digito => "is_digit",
        };
        res.push(format!("{}:{}", pos, tipo));
    }

    fn _features_vizinhanca(
        &self,
        sent: &[&str],
        tokens_info: &[TokenInfo],
        indice_inicial: usize,
        distancia: i32,
        feats: &mut Vec<String>,
    ) {
        assert!(distancia != 0);

        let direcao = if distancia > 0 { 1 } else { -1 };
        let mut posicao_vizinho: Option<usize> = Some(indice_inicial);
        let mut posicao_anterior: Option<usize> = None;

        for _ in 0..distancia.abs() {
            if let Some(pv) = posicao_vizinho {
                posicao_anterior = Some(pv);
                posicao_vizinho = self._pos_prox_palavra(sent, pv, direcao);
            }
        }

        let Some(pos_viz) = posicao_vizinho else {
            return;
        };
        let Some(tok_viz) = tokens_info.get(pos_viz) else {
            return;
        };
        self._token_info_posicional(tok_viz, distancia as i8, feats);

        // A posição geométrica esperada só difere da encontrada quando o
        // vizinho foi alcançado pulando pontuação.
        let posicao_esperada = usize::try_from(indice_inicial as i64 + i64::from(distancia)).ok();
        if posicao_esperada != Some(pos_viz) {
            if let Some(pa) = posicao_anterior {
                let (inicio, fim) = (pa.min(pos_viz), pa.max(pos_viz));
                let tem_pontuacao = sent
                    .get(inicio..=fim)
                    .is_some_and(|faixa| faixa.iter().any(|t| is_pontuacao(t)));
                if tem_pontuacao {
                    feats.push(format!("tem_pontuacao:{}", distancia));
                }
            }
        }
    }

    fn _pos_prox_palavra(
        &self,
        sent: &[&str],
        indice_inicial: usize,
        direcao: i32,
    ) -> Option<usize> {
        let mut i = indice_inicial as i64 + i64::from(direcao);
        loop {
            // Sai pelo `?` assim que o índice passa de qualquer um dos limites
            // (negativo na direção para trás, `sent.len()` na para frente).
            let idx = usize::try_from(i).ok()?;
            let tok = sent.get(idx)?;
            if !tok.is_empty() && tok.chars().all(|c| c.is_alphanumeric()) {
                return Some(idx);
            }
            i += i64::from(direcao);
        }
    }

    // Funções auxiliares de exemplo
    /// Os tokens são fatias emprestadas do texto de entrada: a extração de
    /// features não aloca nenhuma `String` por token.
    pub fn tokenize<'a>(&self, text: &'a str) -> (Vec<&'a str>, Vec<usize>) {
        self.regex_tokenizer
            .find_iter(text)
            .map(|m| (m.as_str(), m.start()))
            .unzip()
    }
}

impl SeparadorEndereco {
    pub fn carregar(caminho: PathBuf) -> Result<SeparadorEndereco, String> {
        let model = Model::from_file(&caminho.to_string_lossy()).map_err(|x| x.to_string())?;

        Ok(SeparadorEndereco {
            model,
            extrator: ExtratorFeature::new(None),
        })
    }

    pub fn tokens2attributes(&self, tokens: &[&str]) -> Vec<Vec<Attribute>> {
        self.extrator.tokens2attributes(tokens)
    }

    fn segmentar(
        &self,
        original: &str,
        tokens: &[&str],
        tags: &[String],
        offsets: &[usize],
    ) -> Vec<SegmentoEndereco> {
        let mut segmentos = Vec::with_capacity(4);
        for ((tok, tok_tipo), offset) in tokens.iter().zip(tags).zip(offsets) {
            // Rótulos são "B_<TIPO>", "I_<TIPO>" ou "O": comparar o byte do BIO
            // evita comparações de string no hot path.
            let Some((bio, tipo)) = tok_tipo.split_once('_') else {
                continue; // "O"
            };

            match bio.as_bytes().first().copied() {
                Some(b'B') => segmentos.push(SegmentoEndereco {
                    valor: tok.to_string(),
                    tipo: tipo.to_ascii_lowercase(),
                }),
                Some(b'I') => {
                    let Some(ultimo_segmento) = segmentos.last_mut() else {
                        continue;
                    };
                    // `eq_ignore_ascii_case` compara sem alocar uma string minúscula
                    // por token "I" (o tipo do segmento já está minúsculo).
                    if !ultimo_segmento.tipo.eq_ignore_ascii_case(tipo) {
                        continue;
                    }
                    let tem_espaco = offset
                        .checked_sub(1)
                        .and_then(|anterior| original.as_bytes().get(anterior))
                        .is_some_and(u8::is_ascii_whitespace);
                    if tem_espaco {
                        ultimo_segmento.valor.push(' ');
                    }
                    ultimo_segmento.valor.push_str(tok);
                }
                _ => continue,
            }
        }

        segmentos
    }

    /// Pipeline completo (tokenização, features, CRF e remontagem dos segmentos).
    ///
    /// `medir` existe para que o caminho sem cronometragem não pague dois
    /// `Instant::now()` por endereço.
    fn processar(
        &self,
        tagger: &mut Tagger<'_>,
        texto: &str,
        medir: bool,
    ) -> (EnderecoSegmentado, Duration, Duration) {
        let (tokens, offsets) = self.extrator.tokenize(texto);

        let inicio_features = medir.then(Instant::now);
        let atributos = self.tokens2attributes(&tokens);
        let duracao_features = inicio_features.map_or(Duration::ZERO, |i| i.elapsed());

        let inicio_inferencia = medir.then(Instant::now);
        let tags = tagger
            .tag(&atributos)
            .expect("Não foi possível executar o tagging do CRF.");
        let duracao_inferencia = inicio_inferencia.map_or(Duration::ZERO, |i| i.elapsed());

        let segmentado = EnderecoSegmentado {
            segmentos: self.segmentar(texto, &tokens, &tags, &offsets),
        };
        (segmentado, duracao_features, duracao_inferencia)
    }

    /// Igual a [`Self::segmentar_endereco`], mas devolve também o tempo gasto na
    /// extração de features e na inferência (tagging) do CRF.
    pub fn segmentar_endereco_com_timing(
        &self,
        texto: &str,
    ) -> (EnderecoSegmentado, Duration, Duration) {
        let mut tagger = self
            .model
            .tagger()
            .expect("Não foi possível criar o tagger do CRF.");
        self.processar(&mut tagger, texto, true)
    }
}

// Em Rust, a constant é criada durante a compilação, então só posso chamar funções muito restritas
// quando uso `const`. Nesse caso,  como tenho uma construção complexa da struct `Padronizador`,
// tenho que usar static com inicialização Lazy (o LazyLock aqui previne condições de corrida).
static SEPARADOR: LazyLock<SeparadorEndereco> = LazyLock::new(|| {
    SeparadorEndereco::carregar(
        obter_modelo(None).expect("Não foi possível obter o caminho do modelo"),
    )
    .expect("Não foi possível carregar o modelo de CRF.")
});

thread_local! {
    /// Um `Tagger` reaproveitado por thread.
    static TAGGER: RefCell<Option<Tagger<'static>>> = const { RefCell::new(None) };
}

/// Executa `f` com o tagger da thread atual, criando-o na primeira chamada.
fn com_tagger<R>(f: impl FnOnce(&mut Tagger<'static>) -> R) -> R {
    TAGGER.with(|celula| {
        let mut celula = celula.borrow_mut();
        let tagger = celula.get_or_insert_with(|| {
            let modelo: &'static Model = &SEPARADOR.model;
            modelo
                .tagger()
                .expect("Não foi possível criar o tagger do CRF.")
        });
        f(tagger)
    })
}

/// Segmenta uma string de  endereço em suas partes constituintes utilizando um modelo
/// probabilístico.
///
/// ```
/// use enderecobr_rs::{Endereco, segmentar_endereco};
/// let endereco_segmentado = segmentar_endereco("av n sra copacabana, 123, apt
/// 301").como_endereco();
/// let endereco_esperado = Endereco { logradouro: Some("av n sra copacabana".to_string()), numero: Some("123".to_string()), complemento: Some("apt 301".to_string()), ..Default::default() };
/// assert_eq!(endereco_segmentado, endereco_esperado);
///
/// let endereco_padronizado_esperado = Endereco { logradouro: Some("AVENIDA NOSSA SENHORA COPACABANA".to_string()), numero: Some("123".to_string()), complemento: Some("APARTAMENTO 301".to_string()), ..Default::default() };
/// assert_eq!(endereco_segmentado.endereco_padronizado(), endereco_padronizado_esperado);
///```
pub fn segmentar_endereco(texto: &str) -> EnderecoSegmentado {
    com_tagger(|tagger| SEPARADOR.processar(tagger, texto, false).0)
}

/// Igual a [`segmentar_endereco`], mas devolve também os tempos gastos na extração
/// de features e na inferência do CRF (útil para medir desempenho).
pub fn segmentar_endereco_com_timing(texto: &str) -> (EnderecoSegmentado, Duration, Duration) {
    com_tagger(|tagger| SEPARADOR.processar(tagger, texto, true))
}

impl EnderecoSegmentado {
    pub fn como_json(&self) -> String {
        serde_json::to_string(&self.segmentos).unwrap_or_else(|_| "[]".to_string())
    }
    pub fn como_endereco(&self) -> Endereco {
        let mut res = Endereco::default();
        for (i, seg) in self.segmentos.iter().enumerate() {
            let atributo_opt = match seg.tipo.as_str() {
                "logradouro" if res.logradouro.is_none() => {
                    Some(res.logradouro.get_or_insert_with(String::new))
                }
                "parcela"
                    if i > 0
                        && self
                            .segmentos
                            .get(i - 1)
                            .filter(|anterior| anterior.tipo == "logradouro")
                            .is_some() =>
                {
                    Some(res.logradouro.get_or_insert_with(String::new))
                }
                // `numero` e `modificador_numero` também alimentam o número.
                "numero" | "modificador_numero" => Some(res.numero.get_or_insert_with(String::new)),
                "quilometragem_via" if res.numero.is_none() => {
                    Some(res.numero.get_or_insert_with(String::new))
                }
                // Sem contexto de número, estes tipos caem no complemento.
                "parcela" | "quilometragem_via" | "complemento" => {
                    Some(res.complemento.get_or_insert_with(String::new))
                }
                "localidade" => Some(res.localidade.get_or_insert_with(String::new)),
                "cep" => Some(res.cep.get_or_insert_with(String::new)),
                _ => None,
            };

            if let Some(atributo) = atributo_opt {
                if !atributo.is_empty() {
                    atributo.push(' ');
                }
                atributo.push_str(seg.valor.as_str());
            }
        }
        res
    }
}

/// Obtém o caminho do modelo de CRF usado por [`segmentar_endereco`], baixando-o
/// do GitHub caso ainda não exista localmente.
///
/// # Destino, em ordem de prioridade
///
/// 1. `path_modelo`, quando informado e não vazio;
/// 2. a variável de ambiente `ENDERECOBR_MODELO_CRF`, quando definida e não
///    vazia;
/// 3. o diretório de cache do sistema operacional (`~/.cache/...` no Linux,
///    `~/Library/Caches` no macOS, `%LOCALAPPDATA%` no Windows), no caminho
///    `enderecobr_rs/<versão do modelo>/tagger.crf`.
///
/// A versão entra no caminho de cache para que uma atualização do modelo não
/// reutilize o arquivo da versão anterior.
///
/// # Arquivo ou diretório
///
/// Tanto `path_modelo` quanto a variável de ambiente aceitam o **arquivo** do
/// modelo ou um **diretório** onde ele deve ser salvo. O caminho é tratado como
/// diretório quando:
///
/// - já existe e é um diretório (`/tmp/modelos`);
/// - termina em separador (`/tmp/modelos/`);
/// - não tem extensão (`/tmp/modelos/v1`).
///
/// Nesses casos `tagger.crf` é anexado ao caminho. Um caminho com extensão
/// (`/tmp/modelos/meu_modelo.crf`) é usado como o próprio arquivo. Diretórios
/// intermediários inexistentes são criados.
///
/// # Download
///
/// O arquivo só é baixado quando está ausente ou vazio (execução anterior
/// interrompida). O download:
///
/// - usa timeout de 60 s para a requisição inteira (conexão + download dos
///   ~1,1 MB);
/// - exige status HTTP de sucesso — sem isso, o corpo de um erro 404/500 seria
///   gravado como se fosse o modelo;
/// - grava primeiro em um temporário no mesmo diretório e o renomeia no fim
///   (atômico no mesmo sistema de arquivos), então duas instâncias baixando ao
///   mesmo tempo não produzem um arquivo corrompido;
/// - avisa uma única vez no `stderr` que está baixando e para onde.
///
/// Defina `ENDERECOBR_MODELO_CRF_SEM_DOWNLOAD=1` para proibir o acesso à rede:
/// nesse modo, um modelo ausente gera erro com a indicação de
/// `ENDERECOBR_MODELO_CRF` — útil em CI, contêineres sem rede e testes.
///
/// # Erros
///
/// Devolve `Err` quando não consegue resolver o destino (sem cache do SO, versão
/// do modelo ilegível na URL), quando o download está proibido ou falha (rede,
/// timeout, status HTTP), quando não consegue criar o diretório, gravar o
/// temporário ou renomeá-lo.
///
/// # Exemplos
///
/// ```no_run
/// # use enderecobr_rs::separador_endereco::obter_modelo;
/// # fn main() -> Result<(), String> {
/// // 1. cache do SO: baixa na primeira execução, reutiliza depois
/// let caminho = obter_modelo(None)?;
///
/// // 2. diretório explícito: termina em `/tmp/modelos/tagger.crf`
/// let caminho = obter_modelo(Some("/tmp/modelos".to_string()))?;
///
/// // 3. arquivo explícito: usado como está
/// let caminho = obter_modelo(Some("/tmp/modelos/meu_modelo.crf".to_string()))?;
/// # let _ = caminho;
/// # Ok(())
/// # }
/// ```
pub fn obter_modelo(path_modelo: Option<String>) -> Result<PathBuf, String> {
    let caminho = resolver_caminho_modelo(path_modelo)?;

    if modelo_disponivel(&caminho) {
        return Ok(caminho);
    }

    baixar_modelo(&caminho)?;
    Ok(caminho)
}

/// Resolve onde o modelo deve ficar, aplicando a ordem de prioridade
/// parâmetro → variável de ambiente → cache do SO.
fn resolver_caminho_modelo(path_modelo: Option<String>) -> Result<PathBuf, String> {
    // Um caminho vazio (`Some("")` ou variável definida em branco) é tratado
    // como ausente: sem isso, `Some("")` viraria um arquivo relativo ao diretório
    // atual, o que quase nunca é a intenção.
    if let Some(caminho) = path_modelo.filter(|caminho| !caminho.is_empty()) {
        return Ok(ajustar_caminho_modelo(PathBuf::from(caminho)));
    }

    if let Some(caminho) = std::env::var_os(VAR_AMBIENTE_MODELO).filter(|valor| !valor.is_empty()) {
        return Ok(ajustar_caminho_modelo(PathBuf::from(caminho)));
    }

    caminho_cache_padrao()
}

/// Caminho padronizado no cache do SO, versionado pelo release do modelo.
fn caminho_cache_padrao() -> Result<PathBuf, String> {
    // `.../download/modelo-crf-v0.1/tagger.crf` -> `modelo-crf-v0.1`.
    let versao = MODEL_DOWNLOAD_PATH
        .rsplit('/')
        .nth(1)
        .ok_or("Não foi possível obter a versão do modelo na URL de download")?;

    Ok(dirs::cache_dir()
        .ok_or("Diretório de cache do sistema operacional indisponível")?
        .join("enderecobr_rs")
        .join(versao)
        .join(MODELO_ARQUIVO))
}

/// Completa o caminho do usuário com `tagger.crf` quando ele aponta para um
/// diretório em vez do arquivo do modelo.
fn ajustar_caminho_modelo(caminho: PathBuf) -> PathBuf {
    if aponta_para_diretorio(&caminho) {
        caminho.join(MODELO_ARQUIVO)
    } else {
        caminho
    }
}

/// `true` quando o caminho só pode ser um diretório: já é um, termina em
/// separador (`/tmp/modelos/`) ou não tem extensão (`/tmp/modelos`).
fn aponta_para_diretorio(caminho: &Path) -> bool {
    caminho.is_dir()
        || caminho.to_string_lossy().ends_with(['/', '\\'])
        || caminho.extension().is_none()
}

/// `true` se há um arquivo utilizável no caminho. Arquivo vazio conta como
/// ausente: é o que resta de uma escrita interrompida.
fn modelo_disponivel(caminho: &Path) -> bool {
    caminho
        .metadata()
        .is_ok_and(|metadados| metadados.is_file() && metadados.len() > 0)
}

/// Baixa o modelo para `destino`, que é criado se ainda não existir.
fn baixar_modelo(destino: &Path) -> Result<(), String> {
    if variavel_ambiente_ativa(VAR_AMBIENTE_SEM_DOWNLOAD) {
        return Err(format!(
            "Modelo de CRF ausente em {} e o download está desativado por \
             {VAR_AMBIENTE_SEM_DOWNLOAD}. Aponte {VAR_AMBIENTE_MODELO} para um \
             arquivo de modelo existente.",
            destino.display()
        ));
    }

    if let Some(diretorio) = destino.parent().filter(|dir| !dir.as_os_str().is_empty()) {
        fs::create_dir_all(diretorio)
            .map_err(|erro| format!("Não foi possível criar {}: {erro}", diretorio.display()))?;
    }

    eprintln!(
        "Baixando o modelo de CRF de {MODEL_DOWNLOAD_PATH} para {}",
        destino.display()
    );

    let bytes = obter_bytes_modelo()?;

    // Temporário único por processo no mesmo diretório do destino: o `rename`
    // final é atômico e duas instâncias concorrentes não se atrapalham.
    let temporario = destino.with_extension(format!("{}.tmp", process::id()));
    fs::write(&temporario, &bytes)
        .map_err(|erro| format!("Não foi possível gravar {}: {erro}", temporario.display()))?;

    fs::rename(&temporario, destino).map_err(|erro| {
        // Não deixamos lixo para trás quando o rename falha.
        descartar_arquivo(&temporario);
        format!(
            "Não foi possível mover {} para {}: {erro}",
            temporario.display(),
            destino.display()
        )
    })
}

/// Baixa o conteúdo do modelo, validando o status HTTP antes de aceitar o corpo.
fn obter_bytes_modelo() -> Result<Vec<u8>, String> {
    let cliente = reqwest::blocking::Client::builder()
        .timeout(TIMEOUT_DOWNLOAD)
        .user_agent(concat!(
            env!("CARGO_PKG_NAME"),
            "/",
            env!("CARGO_PKG_VERSION")
        ))
        .build()
        .map_err(|erro| format!("Não foi possível criar o cliente HTTP: {erro}"))?;

    let resposta = cliente
        .get(MODEL_DOWNLOAD_PATH)
        .send()
        .map_err(|erro| format!("Falha ao baixar o modelo de CRF: {erro}"))?;

    // O `reqwest` só devolve `Err` para falhas de transporte: um 404 ou 500 chega
    // como `Ok` e, sem esta checagem, o HTML do erro viraria o arquivo do modelo.
    let status = resposta.status();
    if !status.is_success() {
        return Err(format!(
            "O download do modelo de CRF falhou com HTTP {status} ({MODEL_DOWNLOAD_PATH})"
        ));
    }

    resposta
        .bytes()
        .map(|bytes| bytes.to_vec())
        .map_err(|erro| format!("Falha ao ler o corpo do download do modelo: {erro}"))
}

/// Variável de ambiente definida com um valor considerado "ligado"
/// (presente, não vazia e diferente de `0`/`false`).
fn variavel_ambiente_ativa(nome: &str) -> bool {
    std::env::var_os(nome).is_some_and(|valor| {
        !valor.is_empty() && valor != "0" && valor != "false"
    })
}

/// Remove um arquivo temporário, ignorando o caso em que ele já não existe.
fn descartar_arquivo(caminho: &Path) {
    match fs::remove_file(caminho) {
        Ok(()) => {}
        Err(erro) if erro.kind() == std::io::ErrorKind::NotFound => {}
        Err(erro) => eprintln!(
            "Aviso: não foi possível remover o arquivo temporário {}: {erro}",
            caminho.display()
        ),
    }
}

// Constantes usadas para criar as features do CRF. Como são consultadas por
// texto já normalizado (emprestado), `&'static str` evita as `String` da
// inicialização sem mudar o custo do lookup (o hash é do conteúdo).

static MARCADORES_CONHECIDOS_DF: LazyLock<FxHashSet<&'static str>> = LazyLock::new(|| {
    FxHashSet::from_iter([
        "SQN", "SQS", "SQNW", "SQSW", "SCLN", "SCLS", "SCN", "SCS", "SGAN", "SGAS", "SEPN", "SEPS",
        "SRTVN", "SRTVS", "SHN", "SHS", "SHIS", "SHIN", "SHLS", "SHLN", "SHCGN", "SHCES", "SHCE",
        "SHTQ", "SMPW", "SAAN", "SAS", "SAUS", "SAUN", "SBS", "SDS", "SDN", "SDMC", "SIG", "SIA",
        "SIBS", "SCES", "SMHN", "SMLN", "SRES", "SRL", "SO", "SOPI", "SOFS", "CLN", "CLS", "CLNW",
        "ADE", "AOS", "AR", "CCSW", "CSG", "CRS", "CSA", "CSB", "CSD", "CNB", "CND", "CNG", "CNL",
        "CNM", "EQ", "EQNM", "EQNO", "EQNP", "EQS", "QI", "QE", "QS", "QR", "QN", "QD", "QNM",
        "QNN", "QNO", "QNP", "QNA", "QNC", "QND", "QNE", "QNF", "QNG", "QNH", "QNJ", "QNL", "QMS",
        "QMSW", "QRC", "QRSW", "QSB", "QSC", "QSE", "QRO", "SIND", "SGCV", "SCE",
    ])
});

static MARCADORES_CONHECIDOS_PALMAS: LazyLock<FxHashSet<&'static str>> = LazyLock::new(|| {
    FxHashSet::from_iter([
        "ARSE", "ARSO", "ARNE", "ARNO", "AC", "ACSE", "ACSO", "ACNE", "ACNO", "ACSU", "ACSV",
        "ASR", "AA", "AAF", "AAE", "AAM", "AANE", "AANO", "AASE", "AASO", "AE", "ALC", "AVNE",
        "AVNO", "AVSE", "AVSO", "APM", "HM", "QI", "QD", "QR", "QC", "LO", "NS",
    ])
});

static SIGLAS_ESTADOS: LazyLock<FxHashSet<&'static str>> =
    LazyLock::new(|| FxHashSet::from_iter(ESTADOS.iter().map(|e| e.sigla)));

#[cfg(test)]
mod tests {
    use super::*;

    fn token2features(sent: &[&str], i: usize) -> Vec<String> {
        ExtratorFeature::new(None).tokens2features(sent)[i].clone()
    }

    fn tokens2features(sent: &[&str]) -> Vec<Vec<String>> {
        ExtratorFeature::new(None).tokens2features(sent)
    }

    fn tokenize(sent: &str) -> Vec<&str> {
        ExtratorFeature::new(None).tokenize(sent).0
    }

    #[test]
    fn test_tokenize_basico() {
        assert_eq!(
            tokenize("Rua das Flores!"),
            vec!["Rua", "das", "Flores", "!"]
        );
        assert_eq!(tokenize("123, teste"), vec!["123", ",", "teste"]);
        assert_eq!(tokenize(""), Vec::<&str>::new());
        assert_eq!(tokenize("A/B"), vec!["A", "/", "B"]);
    }

    #[test]
    fn test_is_pontuacao_casos_basicos() {
        assert!(is_pontuacao(","));
        assert!(is_pontuacao("..."));
        assert!(!is_pontuacao("a"));
        assert!(!is_pontuacao(""));
    }

    #[test]
    fn test_token2features_primeiro_token_basico() {
        let feats = token2features(&["Rua", "das", "Flores"], 0);
        assert!(feats.contains(&"bias".to_string()));
        assert!(feats.contains(&"0_pos".to_string()));
        assert!(feats.contains(&"0:RUA".to_string()));
        assert!(feats.contains(&"0:is_alpha".to_string()));
        assert!(feats.contains(&"0:tam:3".to_string()));
        assert!(feats.contains(&"BOS".to_string()));
        assert!(feats.contains(&"1:DAS".to_string()));
        assert!(feats.contains(&"1:is_alpha".to_string()));
        assert!(feats.contains(&"2:FLORES".to_string()));
        assert!(feats.contains(&"2:is_alpha".to_string()));
        assert!(!feats.contains(&"EOS".to_string()));
    }

    #[test]
    fn test_token2features_token_final() {
        let feats = token2features(&["Rua", "das", "Flores"], 2);
        assert!(feats.contains(&"bias".to_string()));
        assert!(feats.contains(&"EOS".to_string()));
        assert!(feats.contains(&"0:FLORES".to_string()));
        assert!(feats.contains(&"0:is_alpha".to_string()));
        assert!(feats.contains(&"0:tam:6".to_string()));
        assert!(feats.contains(&"-1:DAS".to_string()));
        assert!(feats.contains(&"-1:is_alpha".to_string()));
        assert!(feats.contains(&"-2:RUA".to_string()));
        assert!(feats.contains(&"-2:is_alpha".to_string()));
        assert!(!feats.contains(&"BOS".to_string()));
    }

    #[test]
    fn test_token2features_token_meio_com_digito() {
        let feats = token2features(&["Rua", "123", "Centro"], 1);
        assert!(feats.contains(&"0:is_digit".to_string()));
        assert!(feats.contains(&"0:tam:3".to_string()));
        assert!(feats.contains(&"-1:RUA".to_string()));
        assert!(feats.contains(&"1:CENTRO".to_string()));
        assert!(feats.contains(&"1:is_alpha".to_string()));
        // O token bruto continua entrando; só `digit_len` deixou de existir.
        assert!(feats.contains(&"0:123".to_string()));
        assert!(!feats.iter().any(|f| f.contains("digit_len")));
        assert!(!feats.contains(&"BOS".to_string()));
        assert!(!feats.contains(&"EOS".to_string()));
    }

    #[test]
    fn test_token2features_token_pontuacao() {
        let feats = token2features(&["Rua", ",", "Centro"], 1);
        assert!(feats.contains(&"0:,".to_string()));
        assert!(feats.contains(&"0:is_punct".to_string()));
        assert!(feats.contains(&"-1:RUA".to_string()));
        assert!(feats.contains(&"-1:is_alpha".to_string()));
        assert!(feats.contains(&"1:CENTRO".to_string()));
        assert!(feats.contains(&"1:is_alpha".to_string()));
        assert!(!feats.contains(&"EOS".to_string()));
    }

    #[test]
    fn test_token2features_com_token_alfanumerico() {
        // O tokenizador separa letras de números, então um token alfanumérico
        // não passa de um caso desconhecido (mesma regra do `preproc.py`).
        let feats = token2features(&["Rua", "A1", "Centro"], 1);
        assert!(feats.contains(&"0:A1".to_string()));
        assert!(feats.contains(&"0:is_unknown".to_string()));
        assert!(!feats.contains(&"0:is_alpha".to_string()));
        assert!(feats.contains(&"0:tam:2".to_string()));
        assert!(feats.contains(&"-1:RUA".to_string()));
        assert!(feats.contains(&"1:CENTRO".to_string()));
        assert!(!feats.contains(&"BOS".to_string()));
        assert!(!feats.contains(&"EOS".to_string()));
    }

    #[test]
    fn test_token2features_com_pontuacao_entre_palavras() {
        let feats = token2features(&["Rua", ",", "das", "Flores"], 0);
        assert!(feats.contains(&"0:RUA".to_string()));
        assert!(feats.contains(&"1:DAS".to_string()));
        assert!(feats.contains(&"2:FLORES".to_string()));
        assert!(feats.contains(&"tem_pontuacao:1".to_string()));
        assert!(feats.contains(&"BOS".to_string()));
        assert!(!feats.contains(&"EOS".to_string()));
    }

    #[test]
    fn test_token2features_ignora_pontuacoes_sucessivas() {
        let feats = token2features(&["Rua", ",", ".", "Flores"], 0);
        assert!(feats.contains(&"0:RUA".to_string()));
        assert!(feats.contains(&"1:FLORES".to_string()));
        assert!(feats.contains(&"1:is_alpha".to_string()));
        assert!(feats.contains(&"tem_pontuacao:1".to_string()));
        assert!(feats.contains(&"BOS".to_string()));
        assert!(!feats.contains(&"EOS".to_string()));
    }

    #[test]
    fn test_token2features_palavra_longa() {
        let feats = token2features(&["Inconstitucionalissimamente"], 0);
        assert!(feats.contains(&"0:INCONSTITUCIONALISSIMAMENTE".to_string()));
        assert!(feats.contains(&"0:tam:10".to_string()));
        assert!(feats.contains(&"0:is_alpha".to_string()));
        assert!(feats.contains(&"BOS".to_string()));
        assert!(feats.contains(&"EOS".to_string()));
        assert!(feats.contains(&"bias".to_string()));
    }

    #[test]
    fn test_token2features_todos_pontuacao() {
        let feats = token2features(&[",", ".", ";"], 1);
        assert!(feats.contains(&"0:is_punct".to_string()));
        assert!(feats.contains(&"0:.".to_string()));
        assert!(feats.contains(&"0:tam:1".to_string()));
        assert!(!feats.contains(&"BOS".to_string()));
        assert!(!feats.contains(&"EOS".to_string()));
        assert!(!feats.contains(&"-1:,".to_string()));
        assert!(!feats.contains(&"1:;".to_string()));
    }

    #[test]
    fn test_token2features_com_token_numerico_longo_zeros() {
        // O `tam` de um dígito usa o comprimento sem zeros à esquerda.
        let feats = token2features(&["000000000000012345"], 0);
        assert!(feats.contains(&"0:is_digit".to_string()));
        assert!(feats.contains(&"0:tam:5".to_string()));
        assert!(feats.contains(&"0:000000000000012345".to_string()));
    }

    #[test]
    fn test_token2features_com_token_numerico_longo() {
        let feats = token2features(&["123456789"], 0);
        assert!(feats.contains(&"0:is_digit".to_string()));
        assert!(feats.contains(&"0:tam:9".to_string()));
        assert!(feats.contains(&"BOS".to_string()));
        assert!(feats.contains(&"EOS".to_string()));
        assert!(feats.contains(&"0:123456789".to_string()));
    }

    #[test]
    fn test_token2features_com_pontuacao_longa() {
        let feats = token2features(&["!!!"], 0);
        assert!(feats.contains(&"0:is_punct".to_string()));
        assert!(feats.contains(&"0:!".to_string()));
        assert!(feats.contains(&"BOS".to_string()));
        assert!(feats.contains(&"EOS".to_string()));
    }

    #[test]
    fn test_token2features_token_vazio() {
        let feats = token2features(&[""], 0);
        assert!(feats.contains(&"0:is_unknown".to_string()));
        assert!(feats.contains(&"BOS".to_string()));
        assert!(feats.contains(&"EOS".to_string()));
        assert!(feats.contains(&"0:tam:0".to_string()));
        assert!(!feats.contains(&"0:is_alpha".to_string()));
    }

    #[test]
    fn test_token2features_token_desconhecido() {
        let feats = token2features(&["😀"], 0);
        assert!(feats.contains(&"0:is_unknown".to_string()));
        assert!(!feats.contains(&"0:😀".to_string()));
        assert!(!feats.contains(&"0:is_alpha".to_string()));
        assert!(feats.contains(&"BOS".to_string()));
        assert!(feats.contains(&"EOS".to_string()));
    }

    #[test]
    fn test_token2features_token_com_acentos() {
        let feats = token2features(&["Árvore"], 0);
        assert!(feats.contains(&"0:ARVORE".to_string()));
        assert!(feats.contains(&"0:is_alpha".to_string()));
        assert!(feats.contains(&"0:tam:6".to_string()));
        assert!(feats.contains(&"BOS".to_string()));
        assert!(feats.contains(&"EOS".to_string()));
        assert!(feats.contains(&"bias".to_string()));
    }

    #[test]
    fn test_tokens2features_lista_basica() {
        let feats = tokens2features(&["Rua", "das"]);
        assert_eq!(feats.len(), 2);
        assert!(feats[0].contains(&"0:RUA".to_string()));
        assert!(feats[1].contains(&"0:DAS".to_string()));
    }

    #[test]
    fn test_tokens2features_contem_bias_em_todos() {
        let feats = tokens2features(&["A", "B", "C"]);
        assert!(feats[0].contains(&"bias".to_string()));
        assert!(feats[1].contains(&"bias".to_string()));
        assert!(feats[2].contains(&"bias".to_string()));
    }

    #[test]
    fn test_tokens2features_sem_duplicatas() {
        let feats = tokens2features(&["Rua", ",", "das", "Flores", "123"]);
        for item in &feats {
            let mut ordenado = item.clone();
            ordenado.sort_unstable();
            ordenado.dedup();
            assert_eq!(ordenado.len(), item.len());
        }
    }

    #[test]
    fn test_aponta_para_diretorio() {
        // Sem extensão, com separador final ou diretório existente.
        assert!(aponta_para_diretorio(Path::new("/tmp/modelos")));
        assert!(aponta_para_diretorio(Path::new("/tmp/modelos/")));
        assert!(aponta_para_diretorio(Path::new("src")));
        // Com extensão, o caminho é tratado como o arquivo do modelo.
        assert!(!aponta_para_diretorio(Path::new("/tmp/meu_modelo.crf")));
    }

    #[test]
    fn test_ajustar_caminho_modelo() {
        assert_eq!(
            ajustar_caminho_modelo(PathBuf::from("/tmp/modelos")),
            PathBuf::from("/tmp/modelos/tagger.crf")
        );
        assert_eq!(
            ajustar_caminho_modelo(PathBuf::from("/tmp/modelos/")),
            PathBuf::from("/tmp/modelos/tagger.crf")
        );
        assert_eq!(
            ajustar_caminho_modelo(PathBuf::from("/tmp/meu_modelo.crf")),
            PathBuf::from("/tmp/meu_modelo.crf")
        );
    }

    #[test]
    fn test_modelo_disponivel() {
        // `Cargo.toml` é um arquivo não vazio do próprio repositório.
        assert!(modelo_disponivel(Path::new("Cargo.toml")));
        assert!(!modelo_disponivel(Path::new("nao_existe_modelo.crf")));
        // Um diretório não serve como modelo.
        assert!(!modelo_disponivel(Path::new("src")));
    }

    #[test]
    fn test_caminho_cache_padrao_e_versionado() {
        // Falha só se o SO não expuser um diretório de cache.
        if let Ok(caminho) = caminho_cache_padrao() {
            assert!(caminho.ends_with("enderecobr_rs/modelo-crf-v0.1/tagger.crf"));
        }
    }

    #[test]
    fn test_resolver_caminho_modelo_ordem_de_prioridade() {
        std::env::set_var(VAR_AMBIENTE_MODELO, "/tmp/da_variavel_ambiente.crf");

        let do_parametro = resolver_caminho_modelo(Some("/tmp/do_parametro.crf".to_string()))
            .expect("caminho do parâmetro resolvido");
        let da_variavel =
            resolver_caminho_modelo(None).expect("caminho da variável de ambiente resolvido");

        // Parâmetro e variável vazios são ignorados: cai no cache do SO.
        std::env::set_var(VAR_AMBIENTE_MODELO, "");
        let sem_nenhum = resolver_caminho_modelo(Some(String::new()));
        std::env::remove_var(VAR_AMBIENTE_MODELO);

        assert_eq!(do_parametro, PathBuf::from("/tmp/do_parametro.crf"));
        assert_eq!(
            da_variavel,
            PathBuf::from("/tmp/da_variavel_ambiente.crf")
        );
        assert!(sem_nenhum.is_ok_and(|caminho| caminho.ends_with(MODELO_ARQUIVO)));
    }
}
