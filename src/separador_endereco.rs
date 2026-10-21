pub mod features;
pub mod modelo;

use std::{
    cell::RefCell,
    path::PathBuf,
    sync::LazyLock,
    time::{Duration, Instant},
};

use crfsuite::{Attribute, Model, Tagger};

use serde::Serialize;

pub use crate::separador_endereco::modelo::obter_modelo;
use crate::{separador_endereco::features::ExtratorFeature, Endereco};

pub struct SeparadorEndereco {
    pub model: Model,
    pub extrator: ExtratorFeature,
}

#[derive(Serialize, Debug, PartialEq, Clone)]
pub struct SegmentoEndereco {
    pub valor: String,
    pub tipo: String,
}

#[derive(Serialize, Debug, PartialEq, Clone)]
pub struct EnderecoSegmentado {
    pub segmentos: Vec<SegmentoEndereco>,
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
