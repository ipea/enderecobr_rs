//! # Exemplo de uso
//! ```
//! use enderecobr_rs::{Endereco, segmentar_endereco};
//! let endereco_segmentado = segmentar_endereco("av n sra copacabana, 123, apt
//! 301").como_endereco();
//! let endereco_esperado = Endereco { logradouro: Some("av n sra copacabana".to_string()), numero: Some("123".to_string()), complemento: Some("apt 301".to_string()), ..Default::default() };
//! assert_eq!(endereco_segmentado, endereco_esperado);
//!
//! let endereco_padronizado_esperado = Endereco { logradouro: Some("AVENIDA NOSSA SENHORA COPACABANA".to_string()), numero: Some("123".to_string()), complemento: Some("APARTAMENTO 301".to_string()), ..Default::default() };
//! assert_eq!(endereco_segmentado.endereco_padronizado(), endereco_padronizado_esperado);
//! ```
use std::{
    borrow::Cow,
    cell::RefCell,
    fs,
    path::PathBuf,
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

const MODEL_DOWNLOAD_PATH: &'static str =
    "https://github.com/ipea/enderecobr_rs/releases/download/modelo-crf-v0.1/tagger.crf";

fn is_pontuacao(word: &str) -> bool {
    word.chars().next().is_some_and(|c| PONTUACAO.contains(&c))
}

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
    pub endereco: String,
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
            regex_tokenizer: Regex::new(r"\p{N}+|\p{L}+|[^\s\p{L}\p{N}]").unwrap(),
        }
    }

    pub fn sent2features(&self, text: &str) -> Vec<Vec<String>> {
        let (toks, _) = self.tokenize(text);
        self.tokens2features(&toks)
    }

    pub fn tokens2features(&self, toks: &[String]) -> Vec<Vec<String>> {
        let tok_info: Vec<TokenInfo> = toks.iter().map(|tok| self._token_info(tok)).collect();
        (0..toks.len())
            .map(|i| {
                // Capacidade típica: bias + posição + token + 4 vizinhos.
                let mut feats: Vec<String> = Vec::with_capacity(32);
                self._features_posicao(toks, &tok_info, i, &mut feats);
                // Espelha o `dict.fromkeys` do `preproc.py`: a deduplicação não
                // aloca e a ordem das features é irrelevante para o CRF (soma de pesos).
                feats.sort_unstable();
                feats.dedup();
                feats
            })
            .collect()
    }

    fn _features_posicao(
        &self,
        sent: &[String],
        tokens_info: &[TokenInfo],
        i: usize,
        feats: &mut Vec<String>,
    ) {
        feats.push("bias".to_string());
        feats.push(format!(
            "{}_pos",
            (i as f64 / sent.len() as f64 * 4.0) as i32
        ));
        self._token_info_posicional(&tokens_info[i], 0, feats);

        if i == 0 {
            feats.push("BOS".to_string());
        }
        if i == sent.len() - 1 {
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
        sent: &[String],
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

        if posicao_vizinho.is_none() {
            return;
        }

        let pos_viz = posicao_vizinho.unwrap();
        self._token_info_posicional(&tokens_info[pos_viz], distancia as i8, feats);

        if pos_viz != ((indice_inicial as i32) + distancia) as usize {
            if let Some(pa) = posicao_anterior {
                let faixa = &sent[pa.min(pos_viz)..=pa.max(pos_viz)];
                let tem_pontuacao = faixa.iter().any(|t| is_pontuacao(t));
                if tem_pontuacao {
                    feats.push(format!("tem_pontuacao:{}", distancia));
                }
            }
        }
    }

    fn _pos_prox_palavra(
        &self,
        sent: &[String],
        indice_inicial: usize,
        direcao: i32,
    ) -> Option<usize> {
        let mut i = indice_inicial as i32 + direcao;
        while i >= 0 && (i as usize) < sent.len() {
            let tok = &sent[i as usize];
            if !tok.is_empty() && tok.chars().all(|c| c.is_alphanumeric()) {
                return Some(i as usize);
            }
            i += direcao;
        }
        None
    }

    // Funções auxiliares de exemplo
    pub fn tokenize(&self, text: &str) -> (Vec<String>, Vec<usize>) {
        self.regex_tokenizer
            .find_iter(text)
            .map(|m| (m.as_str().to_string(), m.start()))
            .unzip()
    }
}

impl SeparadorEndereco {
    pub fn carregar(caminho: Option<PathBuf>) -> Result<SeparadorEndereco, String> {
        let modelo_path = caminho.map(Ok).unwrap_or_else(baixar_modelo)?;
        let model = Model::from_file(&modelo_path.to_string_lossy()).map_err(|x| x.to_string())?;

        Ok(SeparadorEndereco {
            model,
            extrator: ExtratorFeature::new(None),
        })
    }

    pub fn tokens2attributes(&self, tokens: &[String]) -> Vec<Vec<Attribute>> {
        self.extrator
            .tokens2features(tokens)
            .into_iter()
            // `Attribute::from(String)` move a String; `Attribute::new(&str, 1.0)`
            // clonaria cada feature, dobrando as alocações por token.
            .map(|feats| feats.into_iter().map(Attribute::from).collect())
            .collect()
    }

    fn segmentar(
        &self,
        original: &str,
        tokens: &[String],
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
        let tags = tagger.tag(&atributos).unwrap();
        let duracao_inferencia = inicio_inferencia.map_or(Duration::ZERO, |i| i.elapsed());

        let segmentado = EnderecoSegmentado {
            endereco: texto.to_string(),
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
        let mut tagger = self.model.tagger().unwrap();
        self.processar(&mut tagger, texto, true)
    }
}

// Em Rust, a constant é criada durante a compilação, então só posso chamar funções muito restritas
// quando uso `const`. Nesse caso,  como tenho uma construção complexa da struct `Padronizador`,
// tenho que usar static com inicialização Lazy (o LazyLock aqui previne condições de corrida).
static SEPARADOR: LazyLock<SeparadorEndereco> = LazyLock::new(|| {
    SeparadorEndereco::carregar(None).expect("Não foi possível carregar o modelo de CRF.")
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
                    Some(res.logradouro.get_or_insert_default())
                }
                "numero" => Some(res.numero.get_or_insert_default()),
                "parcela"
                    if i > 0
                        && self
                            .segmentos
                            .get(i - 1)
                            .filter(|anterior| anterior.tipo == "logradouro")
                            .is_some() =>
                {
                    Some(res.logradouro.get_or_insert_default())
                }
                "parcela" => Some(res.complemento.get_or_insert_default()),
                "modificador_numero" => Some(res.numero.get_or_insert_default()),
                "quilometragem_via" if res.numero.is_none() => {
                    Some(res.numero.get_or_insert_default())
                }
                "quilometragem_via" => Some(res.complemento.get_or_insert_default()),
                "complemento" => Some(res.complemento.get_or_insert_default()),
                "localidade" => Some(res.localidade.get_or_insert_default()),
                "cep" => Some(res.cep.get_or_insert_default()),
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

pub fn baixar_modelo() -> Result<PathBuf, String> {
    let versao_modelo = MODEL_DOWNLOAD_PATH
        .rsplitn(3, "/")
        .nth(1)
        .ok_or("Não foi possivel obter a versão do modelo")?;

    let dir = dirs::cache_dir()
        .ok_or("Diretório de cache indisponível".to_string())?
        .join("enderecobr_rs")
        .join(versao_modelo);

    let path = dir.join("tagger.crf");

    if path.exists() {
        return Ok(path);
    }

    fs::create_dir_all(&dir).map_err(|x| x.to_string())?;

    let bytes = reqwest::blocking::get(MODEL_DOWNLOAD_PATH)
        .map_err(|x| x.to_string())?
        .bytes()
        .map_err(|x| x.to_string())?;

    let tmp = dir.join("tagger.crf.tmp");
    fs::write(&tmp, &bytes).map_err(|x| x.to_string())?;
    fs::rename(&tmp, &path).map_err(|x| x.to_string())?;

    Ok(path)
}

// Constantes usadas para criar as features do CRF.

static MARCADORES_CONHECIDOS_DF: LazyLock<FxHashSet<String>> = LazyLock::new(|| {
    FxHashSet::from_iter(
        [
            "SQN", "SQS", "SQNW", "SQSW", "SCLN", "SCLS", "SCN", "SCS", "SGAN", "SGAS", "SEPN",
            "SEPS", "SRTVN", "SRTVS", "SHN", "SHS", "SHIS", "SHIN", "SHLS", "SHLN", "SHCGN",
            "SHCES", "SHCE", "SHTQ", "SMPW", "SAAN", "SAS", "SAUS", "SAUN", "SBS", "SDS", "SDN",
            "SDMC", "SIG", "SIA", "SIBS", "SCES", "SMHN", "SMLN", "SRES", "SRL", "SO", "SOPI",
            "SOFS", "CLN", "CLS", "CLNW", "ADE", "AOS", "AR", "CCSW", "CSG", "CRS", "CSA", "CSB",
            "CSD", "CNB", "CND", "CNG", "CNL", "CNM", "EQ", "EQNM", "EQNO", "EQNP", "EQS", "QI",
            "QE", "QS", "QR", "QN", "QD", "QNM", "QNN", "QNO", "QNP", "QNA", "QNC", "QND", "QNE",
            "QNF", "QNG", "QNH", "QNJ", "QNL", "QMS", "QMSW", "QRC", "QRSW", "QSB", "QSC", "QSE",
            "QRO", "SIND", "SGCV", "SCE",
        ]
        .iter()
        .map(|x| x.to_string()),
    )
});

static MARCADORES_CONHECIDOS_PALMAS: LazyLock<FxHashSet<String>> = LazyLock::new(|| {
    FxHashSet::from_iter(
        [
            "ARSE", "ARSO", "ARNE", "ARNO", "AC", "ACSE", "ACSO", "ACNE", "ACNO", "ACSU", "ACSV",
            "ASR", "AA", "AAF", "AAE", "AAM", "AANE", "AANO", "AASE", "AASO", "AE", "ALC", "AVNE",
            "AVNO", "AVSE", "AVSO", "APM", "HM", "QI", "QD", "QR", "QC", "LO", "NS",
        ]
        .iter()
        .map(|x| x.to_string()),
    )
});

static SIGLAS_ESTADOS: LazyLock<FxHashSet<String>> =
    LazyLock::new(|| FxHashSet::from_iter(ESTADOS.iter().map(|e| e.sigla.to_string())));

static PONTUACAO: LazyLock<FxHashSet<char>> = LazyLock::new(|| {
    FxHashSet::from_iter("!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~¨´°§¶·«»–—…“”‘’".chars())
});

#[cfg(test)]
mod tests {
    use super::*;

    fn token2features(sent: &[&str], i: usize) -> Vec<String> {
        let toks: Vec<String> = sent.iter().map(|s| s.to_string()).collect();
        ExtratorFeature::new(None).tokens2features(&toks)[i].clone()
    }

    fn tokens2features(sent: &[&str]) -> Vec<Vec<String>> {
        let toks: Vec<String> = sent.iter().map(|s| s.to_string()).collect();
        ExtratorFeature::new(None).tokens2features(&toks)
    }

    fn tokenize(sent: &str) -> Vec<String> {
        ExtratorFeature::new(None).tokenize(sent).0
    }

    #[test]
    fn test_tokenize_basico() {
        assert_eq!(
            tokenize("Rua das Flores!"),
            vec!["Rua", "das", "Flores", "!"]
        );
        assert_eq!(tokenize("123, teste"), vec!["123", ",", "teste"]);
        assert_eq!(tokenize(""), Vec::<String>::new());
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
}
