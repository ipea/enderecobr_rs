use std::borrow::Cow;
use std::io::{self, BufReader, BufWriter};
use std::{cmp::Ordering, f32, fs::File};

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
        self.tokenizer.shrink_to_fit();

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
    pub similaridade_min: Option<f32>,
    pub max_df_freq: Option<f32>,
    pub similaridade_fun: fn(&str, &str) -> f32,
    pub min_qnt_index_scan: Option<usize>,
}

impl Default for SearchParams {
    fn default() -> Self {
        SearchParams {
            sobreposicao_min_tokens: Some(0.5),
            similaridade_min: Some(0.8),
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
        // Pego o índice refente ao município em questão.
        let par_municipio_uf = (
            self.mun_pool.get_str(&padronizar_municipios(municipio))?,
            self.est_pool
                .get_str(padronizar_estados_para_sigla(estado))?,
        );
        let indice_municipio = self.municipios.get(&par_municipio_uf)?;

        let ids_filtro = self.obter_ids_validos(localidade, cep, indice_municipio);

        // Se existem ids de localidade ou CEP, e a entre eles intercessão é vazia,
        // então o resultado do algoritmo é vazio.
        if ids_filtro.as_ref().is_some_and(|ids| ids.is_empty()) {
            return None;
        }

        let logradouro = padronizar_logradouros(logradouro);

        // Caso existam alguma limitação de CEP ou Bairro, considero eles aqui.
        // Senão uso todos os endereços do município.
        let ids_slice = ids_filtro
            .as_deref()
            .unwrap_or(&indice_municipio.idx_logradouro.docs);

        // Caso tenho poucos valores para checar,
        // faço uma consulta sequencial em vez de usar o índice
        if let Some(qtd_index_scan) = params.min_qnt_index_scan {
            if qtd_index_scan >= ids_slice.len() {
                let res = ids_slice
                    .iter()
                    // Trecho comum para localizar o logradouro mais similar
                    .flat_map(|doc_id| self.score_doc(logradouro.as_str(), *doc_id, params))
                    .max();

                return res;
            }
        }

        // Se tenho muitos valores, uso o índice já construído e só mantenho só
        // os endereços solicitados.

        let pular_filtragem = ids_filtro.is_none(); // ignoro o filtro se nem CEP ou Localidade foi
                                                    // informado

        let query: Vec<Token> = self.tokenizer.tokenize_search(&logradouro).collect();
        indice_municipio
            .idx_logradouro
            .buscar(&query, params.sobreposicao_min_tokens, params.max_df_freq)
            .filter(|doc_id| pular_filtragem || ids_slice.binary_search(doc_id).is_ok())
            // Trecho comum para localizar o logradouro mais similar
            .flat_map(|doc_id| self.score_doc(logradouro.as_str(), doc_id, params))
            .max()
    }

    /// Coleta os ids válidos para o par de localidade e CEP de
    /// um dad município.
    /// Retorna None quando não existe nem localidade e nem CEP.
    fn obter_ids_validos<'a>(
        &'a self,
        localidade: Option<&str>,
        cep: Option<&str>,
        indice_municipio: &'a IndiceMunicipio,
    ) -> Option<Cow<'a, [u32]>> {
        let ids_ceps = cep
            .and_then(cep_para_numero)
            .and_then(|x| indice_municipio.por_cep.get(&x));

        let id_localidade = localidade
            .map(padronizar_bairros)
            .and_then(|l| self.loc_pool.get_str(l.as_str()));

        let ids_localidades = id_localidade.and_then(|id| indice_municipio.por_localidade.get(&id));

        match (ids_ceps, ids_localidades) {
            (Some(a), Some(b)) => Some(Cow::Owned(intersect_sorted(a, b))),
            (Some(a), None) => Some(Cow::Borrowed(a)),
            (None, Some(b)) => Some(Cow::Borrowed(b)),
            (None, None) => None,
        }
    }

    fn score_doc(
        &self,
        logradouro: &str,
        doc_id: Doc,
        params: &SearchParams,
    ) -> Option<ScoredDoc<'_>> {
        let doc = self.logr_pool.get(doc_id);
        let sim = (params.similaridade_fun)(logradouro, doc);

        let min_sim = params.similaridade_min.unwrap_or(0.0);
        (sim >= min_sim).then_some(ScoredDoc {
            texto: doc,
            score: sim,
            doc: doc_id,
        })
    }

    // TODO: tratamento de erro!
    pub fn salvar(&self, file_path: &str) -> Result<(), ErroSerdeIndice> {
        let file = File::create(file_path)?;
        let writer = BufWriter::new(file);

        let mut encoder = zstd::Encoder::new(writer, 6)?; // nível 1–22
        postcard::to_io(self, &mut encoder).unwrap();
        encoder.finish()?;

        Ok(())
    }

    // TODO: tratamento de erro!
    pub fn carregar(file_path: &str) -> Result<Self, ErroSerdeIndice> {
        let file = File::open(file_path)?;
        let reader = BufReader::new(file);

        let decompressed = zstd::decode_all(reader)?;

        let value = postcard::from_bytes(&decompressed).unwrap();
        Ok(value)
    }

    pub fn preparar_pools(&mut self) {
        self.loc_pool.popular_inverso();
        self.mun_pool.popular_inverso();
        self.est_pool.popular_inverso();
    }
}

// TODO: Tratamento de erro!
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

// Testes

#[cfg(test)]
mod tests {
    use super::*;

    fn params() -> SearchParams {
        SearchParams {
            similaridade_min: Some(0.0), // facilita match
            ..Default::default()
        }
    }

    fn build_index() -> GeocodeBrIndexer {
        let mut idx = GeocodeBrIndexer::new(3);

        idx.add(
            "SP",
            "SAO PAULO",
            "RUA DAS FLORES",
            Some("CENTRO"),
            Some("70000000"),
        );

        idx.add(
            "SP",
            "SAO PAULO",
            "AVENIDA PAULISTA",
            Some("CENTRO"),
            Some("70000001"),
        );

        idx.add(
            "SP",
            "SAO PAULO",
            "RUA DAS ACACIAS",
            Some("SUL"),
            Some("70000002"),
        );

        idx.finalizar();
        idx
    }

    fn assert_texto_busca(scored: Option<ScoredDoc>, esperado: &str) {
        assert_eq!(scored.map(|x| x.texto), Some(esperado));
    }

    #[test]
    fn busca_basica_sem_filtros() {
        let idx = build_index();

        let res = idx.busca("SP", "SAO PAULO", "RUA DAS FLORES", None, None, &params());
        assert_texto_busca(res, "RUA DAS FLORES");
    }

    #[test]
    fn busca_filtrando_por_cep() {
        let idx = build_index();

        let res = idx.busca(
            "SP",
            "SAO PAULO",
            "RUA DAS FLORES",
            None,
            Some("70000000"),
            &params(),
        );
        assert_texto_busca(res, "RUA DAS FLORES");
    }

    #[test]
    fn busca_filtrando_por_localidade() {
        let idx = build_index();

        let res = idx.busca(
            "SP",
            "SAO PAULO",
            "RUA DAS FLORES",
            Some("CENTRO"),
            None,
            &params(),
        );

        assert_texto_busca(res, "RUA DAS FLORES");
    }

    #[test]
    fn busca_intersecao_vazia_retorna_none() {
        let idx = build_index();

        // CEP de um bairro + localidade de outro
        let res = idx.busca(
            "SP",
            "SAO PAULO",
            "RUA DAS FLORES",
            Some("Sul"),
            Some("70000000"),
            &params(),
        );

        assert!(res.is_none());
    }

    #[test]
    fn busca_municipio_inexistente() {
        let idx = build_index();

        let res = idx.busca(
            "SP",
            "CIDADE INEXISTENTE",
            "RUA DAS FLORES",
            None,
            None,
            &params(),
        );

        assert!(res.is_none());
    }

    #[test]
    fn scored_doc_ordena_por_score_depois_doc() {
        let a = ScoredDoc {
            texto: "A",
            score: 0.9,
            doc: 1,
        };

        let b = ScoredDoc {
            texto: "B",
            score: 0.9,
            doc: 2,
        };

        assert!(a < b);
    }

    #[test]
    fn obter_ids_validos_sem_filtros() {
        let idx = build_index();

        let key = (
            idx.mun_pool.get_str("SAO PAULO").unwrap(),
            idx.est_pool.get_str("SP").unwrap(),
        );

        let mun = idx.municipios.get(&key).unwrap();

        let res = idx.obter_ids_validos(None, None, mun);
        assert!(res.is_none());
    }

    #[test]
    fn salvar_e_carregar_roundtrip() {
        let idx = build_index();

        let path = "/tmp/geocode_test.idx";

        idx.salvar(path).unwrap();
        let mut loaded = GeocodeBrIndexer::carregar(path).unwrap();
        loaded.preparar_pools();

        let res = loaded.busca("SP", "SAO PAULO", "RUA DAS FLORES", None, None, &params());

        assert_texto_busca(res, "RUA DAS FLORES");
    }

    #[test]
    fn caminho_sequencial_quando_slice_pequeno() {
        let idx = build_index();

        let mut p = params();
        p.min_qnt_index_scan = Some(usize::MAX); // força caminho sequencial

        let res = idx.busca("SP", "SAO PAULO", "AVENIDA PAULISTA", None, None, &p);

        assert_texto_busca(res, "AVENIDA PAULISTA");
    }

    // TODO: MOAR TESTES!
}
