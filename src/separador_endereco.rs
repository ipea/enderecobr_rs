pub mod features;
pub mod modelo;

use std::{cell::RefCell, path::PathBuf, sync::LazyLock};

use crfsuite::{Attribute, Model, Tagger};

use serde::Serialize;

pub use crate::separador_endereco::modelo::{obter_caminho_modelo, obter_modelo};
use crate::{
    endereco::{padronizar_in_place, Endereco},
    separador_endereco::features::ExtratorFeature,
};

/// Segmentador de endereços: divide um texto livre em partes (logradouro,
/// número, complemento, CEP etc.) com o auxílio de um modelo treinado.
///
/// Em geral não é preciso criar uma instância: [`segmentar_endereco`] e
/// [`estruturar_endereco`] já usam um modelo padrão compartilhado. Instancie apenas
/// quando quiser trabalhar com um arquivo de modelo próprio.
pub struct SeparadorEndereco {
    /// Modelo usado na classificação dos trechos do endereço.
    pub model: Model,
    /// Responsável por transformar o texto nos atributos lidos pelo modelo.
    pub extrator: ExtratorFeature,
}

/// Um trecho do endereço e o tipo de informação que ele representa.
#[derive(Serialize, Debug, PartialEq, Clone)]
pub struct SegmentoEndereco {
    /// Trecho do endereço, preservando a grafia original.
    pub valor: String,
    /// Tipo do trecho, em minúsculas: `logradouro`, `numero`, `complemento`,
    /// `localidade`, `cep` e outros rótulos do modelo (por exemplo `parcela`,
    /// `modificador_numero` e `quilometragem_via`).
    pub tipo: String,
}

/// Resultado da segmentação: os trechos identificados, na ordem em que aparecem
/// no texto original.
#[derive(Serialize, Debug, PartialEq, Clone)]
pub struct EnderecoSegmentado {
    /// Trechos identificados no endereço.
    pub segmentos: Vec<SegmentoEndereco>,
}

impl SeparadorEndereco {
    /// Cria um separador a partir de um arquivo de modelo já treinado.
    ///
    /// Devolve erro quando o arquivo não existe, não é um modelo válido ou não
    /// consegue ser usado para classificar. Depois de criado, o separador não
    /// falha mais ao segmentar: a única falha restante seria falta de memória,
    /// que já é testada aqui.
    pub fn carregar(caminho: PathBuf) -> Result<SeparadorEndereco, String> {
        let model = Model::from_file(&caminho.to_string_lossy()).map_err(|erro| {
            format!(
                "Não foi possível carregar o modelo {}: {erro}",
                caminho.display()
            )
        })?;

        let separador = SeparadorEndereco {
            model,
            extrator: ExtratorFeature::new(None),
        };

        // Cria um tagger de teste e o descarta: garante já na carga que o modelo
        // é utilizável, para a segmentação em si não ter como falhar.
        drop(separador.novo_tagger());

        Ok(separador)
    }

    /// Converte uma lista de tokens nos atributos que o modelo usa para
    /// classificar cada um. Raramente necessária fora do uso interno.
    pub fn tokens2attributes(&self, tokens: &[&str]) -> Vec<Vec<Attribute>> {
        self.extrator.tokens2attributes(tokens)
    }

    /// Junta os tokens em segmentos, seguindo os rótulos BIO devolvidos pelo modelo.
    fn montar_segmentos(
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

    /// Segmenta um endereço com este separador.
    pub fn segmentar(&self, texto: &str) -> EnderecoSegmentado {
        let mut tagger = self.novo_tagger();
        self.processar_com_tagger(&mut tagger, texto)
    }

    /// Segmenta vários endereços com este separador, reaproveitando o mesmo
    /// tagger entre eles (mais rápido que chamar [`segmentar`](Self::segmentar)
    /// em sequência).
    ///
    /// A saída mantém a ordem da entrada.
    pub fn segmentar_enderecos(&self, textos: &[&str]) -> Vec<EnderecoSegmentado> {
        let mut tagger = self.novo_tagger();
        textos
            .iter()
            .map(|texto| self.processar_com_tagger(&mut tagger, texto))
            .collect()
    }

    /// Cria um tagger para este modelo.
    ///
    /// A criação já foi testada em [`carregar`](Self::carregar), então a única
    /// falha possível aqui seria falta de memória.
    fn novo_tagger(&self) -> Tagger<'_> {
        self.model
            .tagger()
            .expect("Não foi possível criar o tagger do CRF (memória insuficiente)")
    }

    /// Pipeline completo (tokenização, features, modelo e remontagem dos segmentos),
    /// usando um tagger já pronto para ele poder ser reaproveitado.
    fn processar_com_tagger(&self, tagger: &mut Tagger<'_>, texto: &str) -> EnderecoSegmentado {
        let (tokens, offsets) = self.extrator.tokenize(texto);
        let atributos = self.tokens2attributes(&tokens);
        let tags = tagger
            .tag(&atributos)
            .expect("Não foi possível executar o tagging do CRF");

        EnderecoSegmentado {
            segmentos: self.montar_segmentos(texto, &tokens, &tags, &offsets),
        }
    }
}

// Em Rust, a constant é criada durante a compilação, então só posso chamar funções muito restritas
// quando uso `const`. Nesse caso,  como tenho uma construção complexa da struct `Padronizador`,
// tenho que usar static com inicialização Lazy (o LazyLock aqui previne condições de corrida).
// O `Result` guarda a falha (modelo indisponível) para que ela vire um erro comum em
// vez de um panic na primeira chamada.
static SEPARADOR: LazyLock<Result<SeparadorEndereco, String>> =
    LazyLock::new(|| SeparadorEndereco::carregar(obter_modelo(None)?));

/// Devolve o separador padrão, carregado na primeira chamada.
fn separador_padrao() -> Result<&'static SeparadorEndereco, String> {
    SEPARADOR.as_ref().map_err(|erro| erro.clone())
}

thread_local! {
    /// Um `Tagger` reaproveitado por thread.
    static TAGGER: RefCell<Option<Tagger<'static>>> = const { RefCell::new(None) };
}

/// Executa `f` com o tagger da thread atual, criando-o na primeira chamada.
fn com_tagger<R>(
    separador: &'static SeparadorEndereco,
    f: impl FnOnce(&mut Tagger<'static>) -> R,
) -> R {
    TAGGER.with(|celula| {
        let mut celula = celula.borrow_mut();
        let tagger = celula.get_or_insert_with(|| separador.novo_tagger());
        f(tagger)
    })
}

/// Segmenta uma string de endereço em suas partes constituintes utilizando o
/// modelo padrão.
///
/// # Panics
///
/// Panic se o modelo padrão não puder ser obtido ou carregado. Use
/// [`tentar_segmentar_endereco`] para tratar esse caso como erro.
///
/// ```
/// use enderecobr_rs::separador_endereco::{SegmentoEndereco, EnderecoSegmentado, segmentar_endereco, modelo::{VAR_AMBIENTE_SEM_DOWNLOAD, obter_modelo}};
///
/// // Evitando problemas no CI
/// std::env::set_var(VAR_AMBIENTE_SEM_DOWNLOAD, "true");
/// let modelo_existe = obter_modelo(None).map(|x| x.exists()).unwrap_or(false);
/// if !modelo_existe {
///   return;
/// }
///
/// // Exemplo de fato:
/// let endereco_segmentado = segmentar_endereco("av n sra copacabana, 123, apt 301");
/// let endereco_esperado = EnderecoSegmentado {
///     segmentos: Vec::from(&[SegmentoEndereco { valor: "av n sra copacabana".to_string(), tipo: "logradouro".to_string() }, SegmentoEndereco { valor: "123".to_string(), tipo: "numero".to_string() }, SegmentoEndereco { valor: "apt 301".to_string(), tipo: "complemento".to_string() }])
/// };
/// assert_eq!(endereco_segmentado, endereco_esperado);
///```
pub fn segmentar_endereco(texto: &str) -> EnderecoSegmentado {
    tentar_segmentar_endereco(texto).expect("Não foi possível segmentar o endereço")
}

/// Igual a [`segmentar_endereco`], mas devolve o motivo da falha em vez de
/// entrar em panic quando o modelo não está disponível.
pub fn tentar_segmentar_endereco(texto: &str) -> Result<EnderecoSegmentado, String> {
    let separador = separador_padrao()?;
    Ok(com_tagger(separador, |tagger| {
        separador.processar_com_tagger(tagger, texto)
    }))
}

/// Segmenta vários endereços de uma vez, com o modelo padrão carregado uma única
/// vez.
///
/// É a forma mais eficiente de processar uma lista ou coluna de endereços.
///
/// # Panics
///
/// Panic se o modelo padrão não puder ser obtido ou carregado. Use
/// [`tentar_segmentar_enderecos`] para tratar esse caso como erro.
pub fn segmentar_enderecos(textos: &[&str]) -> Vec<EnderecoSegmentado> {
    tentar_segmentar_enderecos(textos).expect("Não foi possível segmentar os endereços")
}

/// Igual a [`segmentar_enderecos`], mas devolve o motivo da falha em vez de
/// entrar em panic quando o modelo não está disponível.
pub fn tentar_segmentar_enderecos(textos: &[&str]) -> Result<Vec<EnderecoSegmentado>, String> {
    let separador = separador_padrao()?;
    Ok(com_tagger(separador, |tagger| {
        textos
            .iter()
            .map(|texto| separador.processar_com_tagger(tagger, texto))
            .collect()
    }))
}

impl EnderecoSegmentado {
    /// Serializa os segmentos em JSON. Equivalente a [`segmento_como_json`].
    pub fn como_json(&self) -> String {
        segmento_como_json(self)
    }

    /// Junta os segmentos em um [`Endereco`], padronizando os campos quando
    /// `padronizar` for verdadeiro. Equivalente a [`segmento_como_endereco`].
    pub fn como_endereco(&self, padronizar: bool) -> Endereco {
        segmento_como_endereco(self, padronizar)
    }
}

/// Junta os segmentos em um [`Endereco`] e devolve os campos já separados.
///
/// `padronizar` indica se os campos resultantes devem passar pelas funções de
/// padronização.
///
/// # Panics
///
/// Panic se o modelo padrão não puder ser carregado. Use
/// [`tentar_estruturar_endereco`] para tratar esse caso como erro.
pub fn estruturar_endereco(endereco: &str, padronizar: bool) -> Endereco {
    tentar_estruturar_endereco(endereco, padronizar)
        .expect("Não foi possível estruturar o endereço")
}

/// Igual a [`estruturar_endereco`], mas devolve o motivo da falha em vez de
/// entrar em panic quando o modelo não está disponível.
pub fn tentar_estruturar_endereco(endereco: &str, padronizar: bool) -> Result<Endereco, String> {
    tentar_segmentar_endereco(endereco)
        .map(|segmentado| segmento_como_endereco(&segmentado, padronizar))
}

/// Serializa os segmentos encontrados em JSON.
pub fn segmento_como_json(segmentado: &EnderecoSegmentado) -> String {
    serde_json::to_string(segmentado).unwrap_or_else(|_| "[]".to_string())
}

/// Agrupa os segmentos nos campos de um [`Endereco`].
///
/// Trechos sem campo próprio são encaixados conforme o contexto: `parcela`
/// logo após um logradouro continua no logradouro; `parcela`,
/// `quilometragem_via` e `complemento` vão para o complemento; e
/// `modificador_numero` acompanha o número.
pub fn segmento_como_endereco(segmentado: &EnderecoSegmentado, padronizar: bool) -> Endereco {
    let mut res = Endereco::default();
    for (i, seg) in segmentado.segmentos.iter().enumerate() {
        let atributo_opt = match seg.tipo.as_str() {
            "logradouro" if res.logradouro.is_none() => {
                Some(res.logradouro.get_or_insert_with(String::new))
            }
            "parcela"
                if i > 0
                    && segmentado
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
    if padronizar {
        padronizar_in_place(&mut res);
    }

    res
}
