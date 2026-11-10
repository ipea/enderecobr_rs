//! Fachada fina sobre a biblioteca de CRF.
//!
//! Só este módulo conhece o crate que faz a inferência: carregar o modelo, rodar
//! o Viterbi e ler as probabilidades marginais. O resto do separador trabalha com
//! nomes de feature (as `String` do [`ExtratorFeature`](super::features::ExtratorFeature))
//! e com os rótulos em texto, então trocar de biblioteca é reescrever só o que
//! está aqui.

use std::{path::Path, sync::Arc};

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
    pub fn tagger(&self) -> Tagger<'_> {
        Tagger {
            modelo: self,
            interno: Crf1dTagger::new(&self.leitor),
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
pub struct Sequencia {
    /// Rótulo previsto para cada token.
    pub rotulos: Vec<String>,
    /// Probabilidade marginal do rótulo previsto em cada token.
    pub marginais: Vec<f64>,
    /// Log da função de partição da sequência.
    pub lognorm: f64,
    /// Score do caminho de Viterbi.
    pub score: f64,
}

/// Tagger de um [`Modelo`], reaproveitável entre sequências.
pub struct Tagger<'a> {
    modelo: &'a Modelo,
    interno: Crf1dTagger<'a>,
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

    /// Rótulos e, para cada token, a marginal do rótulo previsto.
    pub fn estimar(&mut self, features: &[Vec<String>]) -> Sequencia {
        let instancia = self.modelo.montar_instancia(features);
        if instancia.items.is_empty() {
            return Sequencia {
                rotulos: Vec::new(),
                marginais: Vec::new(),
                lognorm: 0.0,
                score: 0.0,
            };
        }
        self.interno.set(&instancia);
        let (ids, score) = self.interno.viterbi();
        let lognorm = self.interno.lognorm();
        let marginais = ids
            .iter()
            .enumerate()
            .map(|(posicao, &id)| self.interno.marginal_point(id, posicao as i32))
            .collect();
        Sequencia {
            rotulos: ids.iter().map(|&id| self.modelo.rotulo(id)).collect(),
            marginais,
            lognorm,
            score,
        }
    }
}
