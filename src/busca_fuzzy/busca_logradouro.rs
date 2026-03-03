use std::io;
use std::{cmp::Ordering, f32, fs::File, io::BufWriter};

use crate::busca_fuzzy::indice_invertido::{Doc, InvertedIndex};
use crate::busca_fuzzy::string_pool::StringPool;
use crate::busca_fuzzy::tokenizer::{NgramTokenizer, Token};
use crate::busca_fuzzy::utils::intersect_sorted;
use crate::cep::cep_para_numero;
use crate::{
    padronizar_bairros, padronizar_estados_para_sigla, padronizar_logradouros,
    padronizar_municipios,
};
use rustc_hash::FxHashMap;
use serde::{Deserialize, Serialize};

///////////////

type Cep = u32;
type LocalidadeId = u32;

#[derive(Serialize, Deserialize, Clone)]
struct IndiceMunicipio {
    pub por_cep: FxHashMap<Cep, Vec<Doc>>,
    pub por_localidade: FxHashMap<LocalidadeId, Vec<Doc>>,
    pub idx_logradouro: InvertedIndex,
}

impl IndiceMunicipio {
    fn new() -> Self {
        IndiceMunicipio {
            por_cep: FxHashMap::default(),
            por_localidade: FxHashMap::default(),
            idx_logradouro: InvertedIndex::default(),
        }
    }
}

#[derive(Serialize, Deserialize, Clone)]
pub struct GeocodeBrIndexer {
    loc_pool: StringPool,
    mun_pool: StringPool,
    est_pool: StringPool,
    logr_pool: StringPool,
    municipios: FxHashMap<(u32, u32), IndiceMunicipio>,
    tokenizer: NgramTokenizer,
}

impl GeocodeBrIndexer {
    pub fn new(ngram_size: usize) -> Self {
        GeocodeBrIndexer {
            loc_pool: StringPool::default(),
            mun_pool: StringPool::default(),
            est_pool: StringPool::default(),
            logr_pool: StringPool::default(),
            municipios: FxHashMap::default(),
            tokenizer: NgramTokenizer::new(ngram_size),
        }
    }
    pub fn add(
        &mut self,
        estado: &str,
        municipio: &str,
        logradouro: &str,
        localidade: Option<&str>,
        cep: Option<&str>,
    ) {
        let idx_municipio = self
            .municipios
            .entry((self.mun_pool.push(municipio), self.est_pool.push(estado)))
            .or_insert(IndiceMunicipio::new());

        let tokens: Vec<Token> = self.tokenizer.tokenize_index(logradouro).collect();
        let logradouro_id = self.logr_pool.push(logradouro);

        idx_municipio.idx_logradouro.add(&tokens, logradouro_id);

        if let Some(loc) = localidade {
            let localidade_id = self.loc_pool.push(loc);

            let indice_localidade = idx_municipio
                .por_localidade
                .entry(localidade_id)
                .or_default();

            indice_localidade.push(logradouro_id);
        }

        if let Some(cep_num) = cep.and_then(cep_para_numero) {
            let indice_cep = idx_municipio.por_cep.entry(cep_num).or_default();
            indice_cep.push(logradouro_id);
        }
    }

    pub fn finalizar(&mut self) {
        self.loc_pool.shrink_to_fit();
        self.mun_pool.shrink_to_fit();
        self.est_pool.shrink_to_fit();

        self.logr_pool.inverso.clear();
        self.logr_pool.shrink_to_fit();

        self.municipios.shrink_to_fit();
        self.tokenizer.token_map.shrink_to_fit();

        for municipio in self.municipios.values_mut() {
            municipio.idx_logradouro.finalizar();

            for cep in municipio.por_cep.values_mut() {
                cep.sort_unstable();
                cep.dedup();
            }

            for loc in municipio.por_localidade.values_mut() {
                loc.sort_unstable();
                loc.dedup();
            }
        }
    }
}

pub struct SearchParams {
    pub sobreposicao_min_tokens: Option<f32>,
    pub similaridade_min: f32,
    pub max_df_freq: Option<f32>,
    pub similaridade_fun: fn(&str, &str) -> f32,
    pub min_qnt_index_scan: Option<usize>,
}

impl Default for SearchParams {
    fn default() -> Self {
        SearchParams {
            sobreposicao_min_tokens: Some(0.5),
            similaridade_min: 0.8,
            max_df_freq: Some(0.1),
            similaridade_fun: |a, b| strsim::jaro(a, b) as f32,
            min_qnt_index_scan: Some(50),
        }
    }
}

/// Estrutura usada na resposta do motor de busca com
/// capacidade de ordenação por score e doc_id.
#[derive(Debug)]
pub struct ScoredDoc<'a> {
    pub texto: &'a str,
    pub score: f32,
    pub doc: Doc,
}

impl<'a> PartialEq for ScoredDoc<'a> {
    fn eq(&self, other: &Self) -> bool {
        self.score.total_cmp(&other.score) == Ordering::Equal
    }
}

impl<'a> Eq for ScoredDoc<'a> {}

impl<'a> PartialOrd for ScoredDoc<'a> {
    fn partial_cmp(&self, other: &Self) -> Option<Ordering> {
        Some(self.cmp(other))
    }
}

impl<'a> Ord for ScoredDoc<'a> {
    fn cmp(&self, other: &Self) -> Ordering {
        self.score
            .total_cmp(&other.score)
            .then_with(|| self.doc.cmp(&other.doc))
    }
}

impl GeocodeBrIndexer {
    pub fn busca(
        &self,
        estado: &str,
        municipio: &str,
        logradouro: &str,
        localidade: Option<&str>,
        cep: Option<&str>,
        params: &SearchParams,
    ) -> Option<ScoredDoc<'_>> {
        //

        let indice = self.municipios.get(&(
            self.mun_pool.get_str(&padronizar_municipios(municipio))?,
            self.est_pool
                .get_str(padronizar_estados_para_sigla(estado))?,
        ))?;

        let ids_ceps = cep
            .and_then(cep_para_numero)
            .and_then(|x| indice.por_cep.get(&x));

        let id_localidade = localidade
            .map(padronizar_bairros)
            .and_then(|l| self.loc_pool.get_str(l.as_str()));

        let ids_localidades = id_localidade.and_then(|id| indice.por_localidade.get(&id));

        let ids_filtro: Option<&Vec<Doc>> = match (ids_ceps, ids_localidades) {
            (Some(a), Some(b)) => Some(&intersect_sorted(a, b)),
            (Some(a), None) => Some(a),
            (None, Some(b)) => Some(b),
            (None, None) => None,
        };

        // Se existem ids de localidade ou CEP, e a entre eles intercessão é vazia,
        // então o resultado do algoritmo é vazio.
        if ids_filtro.is_some_and(|ids| ids.is_empty()) {
            return None;
        }

        let logradouro = padronizar_logradouros(logradouro);

        // Caso existam alguma limitação de CEP ou Bairro, uso a intercessão aqui.
        // Senão uso todos os endereços do município.
        let ids_seq_scan = ids_filtro.unwrap_or(&indice.idx_logradouro.docs);

        // Caso tenho poucos valores para checar,
        // faço uma consulta sequencial em vez de usar o índice
        if let Some(qtd_index_scan) = params.min_qnt_index_scan {
            if qtd_index_scan >= ids_seq_scan.len() {
                let res = ids_seq_scan
                    .iter()
                    // Trecho comum para localizar o logradouro mais similar
                    .flat_map(|doc_id| self.score_doc(logradouro.as_str(), *doc_id, params))
                    .max();

                return res;
            }
        }

        // Se tenho muitos valores, uso o índice já construído e só mantenho só
        // os endereços solicitados.
        let query: Vec<Token> = self.tokenizer.tokenize_search(&logradouro).collect();
        indice
            .idx_logradouro
            .buscar(&query, params.sobreposicao_min_tokens, params.max_df_freq)
            .filter(|doc_id| {
                ids_filtro
                    .as_ref()
                    .map_or(true, |ids| ids.binary_search(doc_id).is_ok())
            })
            // Trecho comum para localizar o logradouro mais similar
            .flat_map(|doc_id| self.score_doc(logradouro.as_str(), doc_id, params))
            .max()
    }

    fn score_doc(
        &self,
        logradouro: &str,
        doc_id: Doc,
        params: &SearchParams,
    ) -> Option<ScoredDoc<'_>> {
        let doc = self.logr_pool.get(doc_id);
        let sim = (params.similaridade_fun)(logradouro, doc);
        (sim >= params.similaridade_min).then_some(ScoredDoc {
            texto: doc,
            score: sim,
            doc: doc_id,
        })
    }

    pub fn salvar(&self, file_path: &str) -> Result<(), ErroSerdeIndice> {
        let file = File::create(file_path)?;
        let mut writer = BufWriter::with_capacity(10 * 1024 * 1024, file);
        rmp_serde::encode::write_named(writer.get_mut(), self)?;
        Ok(())
    }

    pub fn carregar(file_path: &str) -> Result<Self, ErroSerdeIndice> {
        let file = File::open(file_path)?;
        let reader = std::io::BufReader::with_capacity(10 * 1024 * 1024, file);
        let res = rmp_serde::decode::from_read(reader)?;
        Ok(res)
    }

    pub fn preparar_pools(&mut self) {
        self.loc_pool.popular_inverso();
        self.mun_pool.popular_inverso();
        self.est_pool.popular_inverso();
    }
}

#[derive(Debug)]
pub enum ErroSerdeIndice {
    Io(io::Error),
    Encode(rmp_serde::encode::Error),
    Decode(rmp_serde::decode::Error),
}

impl From<io::Error> for ErroSerdeIndice {
    fn from(e: io::Error) -> Self {
        Self::Io(e)
    }
}

impl From<rmp_serde::encode::Error> for ErroSerdeIndice {
    fn from(e: rmp_serde::encode::Error) -> Self {
        Self::Encode(e)
    }
}

impl From<rmp_serde::decode::Error> for ErroSerdeIndice {
    fn from(e: rmp_serde::decode::Error) -> Self {
        Self::Decode(e)
    }
}
