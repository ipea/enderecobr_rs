//! Fachada fina sobre a biblioteca de CRF.
//!
//! Só este módulo conhece o crate que faz a inferência: carregar o modelo, rodar
//! o Viterbi e ler as probabilidades marginais. O resto do separador trabalha com
//! nomes de feature (as `String` do [`ExtratorFeature`](super::features::ExtratorFeature))
//! e com os rótulos em texto, então trocar de biblioteca é reescrever só o que
//! está aqui.

use std::{ops::Range, path::Path, sync::Arc};

use crfsuite_compliant_rs::{
    crf1d::tag::Crf1dTagger,
    model::ModelReader,
    types::{Attribute, Instance, Item},
};

/// Modelo CRF carregado de um arquivo `.crf`.
///
/// O leitor empresta os bytes do arquivo, então os dois vivem juntos aqui. A
/// ordem dos campos importa: `leitor` é declarado antes e, portanto, cai antes
/// de `_dados`.
pub struct Modelo {
    leitor: ModelReader<'static>,
    _dados: Arc<[u8]>,
}

impl Modelo {
    /// Abre um arquivo de modelo. Devolve erro quando o arquivo não pode ser
    /// lido ou não é um modelo de CRF.
    pub fn carregar(caminho: &Path) -> Result<Modelo, String> {
        let dados: Arc<[u8]> = std::fs::read(caminho)
            .map_err(|erro| format!("Não foi possível ler {}: {erro}", caminho.display()))?
            .into();
        let leitor = ModelReader::open(&dados)
            .ok_or_else(|| format!("Não é um modelo de CRF válido: {}", caminho.display()))?;
        // SAFETY: o buffer é do `Arc` que acompanha o leitor, sua alocação não
        // se move nem muda depois da carga, e o leitor cai antes dele.
        let leitor: ModelReader<'static> = unsafe { std::mem::transmute(leitor) };
        Ok(Modelo {
            leitor,
            _dados: dados,
        })
    }

    /// Cria um tagger reaproveitável. Cada thread deve ter o seu.
    pub fn novo_tagger(&self) -> Tagger<'_> {
        Tagger {
            modelo: self,
            interno: Crf1dTagger::new(&self.leitor),
            ultimo_caminho: Vec::new(),
        }
    }

    fn rotulo(&self, id: i32) -> String {
        self.leitor.to_label(id).unwrap_or_default().to_string()
    }

    /// Traduz features em atributos do modelo. Feature desconhecida fica de
    /// fora, como faria o CRF original.
    fn montar_instancia(&self, features: &[Vec<String>]) -> Instance {
        let mut instancia = Instance::new();
        for nomes in features {
            let mut item = Item::new();
            for nome in nomes {
                if let Some(aid) = self.leitor.to_aid(nome) {
                    item.contents.push(Attribute { aid, value: 1.0 });
                }
            }
            instancia.items.push(item);
        }
        instancia
    }
}

/// Rótulos de uma sequência, com as probabilidades quando pedidas.
pub struct Estimativa {
    /// Rótulo previsto para cada token.
    pub rotulos: Vec<String>,
    /// Probabilidade marginal do rótulo previsto em cada token.
    pub marginais: Vec<f64>,
    /// Probabilidade de a rotulagem da sequência inteira estar correta.
    pub probabilidade: f64,
    /// Média geométrica das marginais dos rótulos previstos: a certeza por token,
    /// já normalizada pelo tamanho da sequência.
    pub confianca: f64,
}

/// Tagger de um [`Modelo`], reaproveitável entre sequências.
pub struct Tagger<'a> {
    modelo: &'a Modelo,
    interno: Crf1dTagger<'a>,
    /// Rótulos da última sequência estimada, que as probabilidades de trecho
    /// precisam para saber qual caminho medir.
    ultimo_caminho: Vec<i32>,
}

impl Tagger<'_> {
    /// Rótulo previsto para cada token. Só roda o Viterbi.
    pub fn rotular(&mut self, features: &[Vec<String>]) -> Vec<String> {
        let instancia = self.modelo.montar_instancia(features);
        if instancia.items.is_empty() {
            return Vec::new();
        }
        self.interno.set(&instancia);
        let (ids, _) = self.interno.viterbi();
        ids.iter().map(|&id| self.modelo.rotulo(id)).collect()
    }

    /// Rótulos, marginais por token e as probabilidades da sequência.
    ///
    /// As marginais saem da passada forward/backward, que é a parte cara
    /// ([`rotular`](Self::rotular) não a faz) e deixa o tagger pronto para
    /// [`probabilidade_trecho`](Self::probabilidade_trecho).
    pub fn rotular_com_probabilidades(&mut self, features: &[Vec<String>]) -> Estimativa {
        let instancia = self.modelo.montar_instancia(features);
        if instancia.items.is_empty() {
            self.ultimo_caminho.clear();
            return Estimativa {
                rotulos: Vec::new(),
                marginais: Vec::new(),
                probabilidade: 0.0,
                confianca: 0.0,
            };
        }
        self.interno.set(&instancia);
        let (ids, _) = self.interno.viterbi();
        let marginais: Vec<f64> = ids
            .iter()
            .enumerate()
            .map(|(posicao, &id)| self.interno.marginal_point(id, posicao as i32))
            .collect();
        let probabilidade = self.interno.marginal_path(&ids, 0, ids.len() as i32);
        let confianca = media_geometrica(&marginais);
        let rotulos: Vec<String> = ids.iter().map(|&id| self.modelo.rotulo(id)).collect();
        self.ultimo_caminho = ids;
        Estimativa {
            rotulos,
            marginais,
            probabilidade,
            confianca,
        }
    }

    /// Probabilidade de cada faixa de tokens `[inicio, fim)` ficar exatamente com
    /// os rótulos previstos por
    /// [`rotular_com_probabilidades`](Self::rotular_com_probabilidades), com o
    /// resto da sequência marginalizado.
    ///
    /// Uma faixa de três tokens devolve `P(y₁, y₂, y₃ | x)`, não o produto das
    /// marginais de cada um. Só vale para a última sequência estimada.
    pub fn probabilidade_trecho(&mut self, faixas: &[Range<usize>]) -> Vec<f64> {
        faixas
            .iter()
            .map(|faixa| {
                if faixa.is_empty() {
                    return 0.0;
                }
                self.interno.marginal_path(
                    &self.ultimo_caminho,
                    faixa.start as i32,
                    faixa.end as i32,
                )
            })
            .collect()
    }
}

/// Média geométrica das probabilidades: `exp(mean(ln p))`. Devolve 0 quando a
/// lista está vazia ou alguma probabilidade é 0.
fn media_geometrica(probabilidades: &[f64]) -> f64 {
    if probabilidades.is_empty() {
        return 0.0;
    }
    let media_log =
        probabilidades.iter().map(|p| p.ln()).sum::<f64>() / probabilidades.len() as f64;
    media_log.exp()
}

#[cfg(test)]
mod tests {
    use super::{media_geometrica, Modelo};
    use crate::separador_endereco::modelo::obter_modelo_no_cache;
    use crate::separador_endereco::SeparadorEndereco;

    /// Todo atributo do modelo precisa voltar pelo próprio nome.
    ///
    /// O binding antigo hasheava nomes de exatamente 12 caracteres no balde
    /// errado: `to_aid` devolvia `None`, o atributo era descartado em silêncio e
    /// 237 deles nunca chegavam ao tagger.
    #[test]
    fn media_geometrica_nao_e_a_aritmetica_nem_o_produto() {
        // (0.98 * 0.55)^(1/2) = 0.7342; a aritmética seria 0.765 e o produto 0.539.
        assert!((media_geometrica(&[0.98, 0.55]) - 0.734166).abs() < 1e-6);
        assert!((media_geometrica(&[0.5, 0.5]) - 0.5).abs() < 1e-12);
        assert!((media_geometrica(&[0.25, 0.25, 0.25, 0.25]) - 0.25).abs() < 1e-12);
        assert!((media_geometrica(&[1.0]) - 1.0).abs() < 1e-12);
        assert!(media_geometrica(&[]).abs() < 1e-12);
    }

    #[test]
    fn todo_atributo_volta_pelo_proprio_nome() {
        let Some(caminho) = obter_modelo_no_cache() else {
            return;
        };
        let modelo = Modelo::carregar(&caminho).unwrap();

        let ids: Vec<Option<i32>> = (0..modelo.leitor.num_attrs() as i32)
            .filter_map(|id| modelo.leitor.to_attr(id))
            .map(|nome| modelo.leitor.to_aid(nome))
            .collect();
        let esperados: Vec<Option<i32>> = (0..modelo.leitor.num_attrs() as i32).map(Some).collect();
        assert_eq!(ids, esperados);
    }

    #[test]
    fn estimar_devolve_marginal_do_rotulo_previsto() {
        let Some(caminho) = obter_modelo_no_cache() else {
            return;
        };
        let separador = SeparadorEndereco::carregar(caminho).unwrap();
        let (tokens, _) = separador.extrator.tokenize("rua brasil, 123");
        let features = separador.extrator.tokens2features(&tokens);

        let mut tagger = separador.modelo.novo_tagger();
        let estimativa = tagger.rotular_com_probabilidades(&features);
        let trechos = tagger.probabilidade_trecho(&[0..1, 1..3]);

        assert_eq!(estimativa.rotulos.len(), tokens.len());
        assert_eq!(estimativa.marginais.len(), tokens.len());
        assert!(estimativa.marginais.iter().all(|m| (0.0..=1.0).contains(m)));
        assert!(estimativa.marginais.iter().all(|m| *m > 0.0));
        assert!(estimativa.probabilidade > 0.0 && estimativa.probabilidade <= 1.0);
        assert_eq!(trechos.len(), 2);
        assert!((0.0..=1.0).contains(&estimativa.probabilidade));
        // A probabilidade de um trecho nunca é menor que a da sequência inteira.
        assert!(trechos
            .iter()
            .all(|trecho| *trecho >= estimativa.probabilidade));
    }
}
