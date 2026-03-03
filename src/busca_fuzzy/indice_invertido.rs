use rustc_hash::FxHashMap;
use serde::{Deserialize, Serialize};

use crate::busca_fuzzy::tokenizer::Token;

pub type Doc = u32;
type Contagem = u16;

pub struct SearchIterator<'a> {
    min_overlap: Contagem,
    contagem: Vec<Contagem>,
    ativos: Vec<InternalDocId>,
    docs_ids_externo: &'a [Doc],
    pos: usize,
}

impl<'a> SearchIterator<'a> {
    fn vazio() -> Self {
        SearchIterator {
            min_overlap: 0,
            contagem: Vec::new(),
            ativos: Vec::new(),
            docs_ids_externo: &[],
            pos: 0,
        }
    }
    fn new(min_overlap: Contagem, capacity: usize, docs: &'a [Doc]) -> Self {
        SearchIterator {
            min_overlap,
            contagem: vec![0; capacity],
            ativos: Vec::with_capacity(capacity / 10),
            docs_ids_externo: docs,
            pos: 0,
        }
    }
}

impl<'a> Iterator for SearchIterator<'a> {
    type Item = Doc;

    fn next(&mut self) -> Option<Self::Item> {
        while self.pos < self.ativos.len() {
            let doc_id = self.ativos[self.pos];
            self.pos += 1;

            // Pulo o documento caso a quantidade de tokens sobrepostos
            // entre ele e a query não bata a meta
            let qtd = self.contagem[doc_id as usize];
            if qtd >= self.min_overlap {
                return Some(self.docs_ids_externo[doc_id as usize]);
            }
        }
        None
    }
}

type InternalDocId = u16;

#[derive(Serialize, Deserialize, Clone, Default)]
pub struct InvertedIndex {
    pub buckets: FxHashMap<Token, Vec<InternalDocId>>,
    pub docs_to_id: FxHashMap<Doc, InternalDocId>,
    pub docs: Vec<Doc>,
}

impl InvertedIndex {
    pub fn add(&mut self, tokens: &[Token], doc: Doc) {
        let novo_doc_id = self.docs_to_id.len();

        let doc_id = self
            .docs_to_id
            .entry(doc)
            .or_insert(novo_doc_id as InternalDocId);

        for t in tokens {
            self.buckets.entry(*t).or_default().push(*doc_id);
        }
    }

    pub fn finalizar(&mut self) {
        for bucket in self.buckets.values_mut() {
            bucket.sort_unstable();
            bucket.shrink_to_fit();
        }
        self.buckets.shrink_to_fit();

        let mut docs: Vec<(&Doc, &InternalDocId)> = self.docs_to_id.iter().collect();
        docs.sort_unstable_by_key(|d| d.1);
        self.docs = docs.iter().map(|x| *x.0).collect();

        self.docs.shrink_to_fit();
        self.docs_to_id = FxHashMap::default();
    }

    fn frequencia_token(&self, token: &Token) -> Contagem {
        self.buckets.get(token).map(|p| p.len()).unwrap_or(0) as Contagem
    }

    fn total_docs(&self) -> usize {
        self.docs.len()
    }

    /// Avalia em quantos documentos diferentes o token poderia existir,
    /// sem se tornar ruído (ex: RUA no contexto de logradouros).
    fn max_freq_aceitavel(&self, max_df_freq: Option<f32>) -> Contagem {
        max_df_freq
            .map(|max_df| (self.total_docs() as f32 * max_df).ceil() as Contagem)
            .unwrap_or(Contagem::MAX)
    }

    /// Preparo a query final já descartando alguns tokens muito frequentes.
    /// E ordenando pela quantidade de documentos em que ele aparece,
    /// afim de priorizar as contagens.
    fn preparar_query(
        &self,
        query: &[Token],
        max_freq_aceitavel: Contagem,
    ) -> Vec<(Token, Contagem)> {
        let mut query_final: Vec<(Token, Contagem)> = query
            .iter()
            .filter_map(|t| {
                let freq = self.frequencia_token(t);
                (freq > 0 && freq < max_freq_aceitavel).then_some((*t, freq))
            })
            .collect();

        if query_final.len() < 3 {
            query_final = query
                .iter()
                .map(|t| (*t, self.frequencia_token(t)))
                .collect();
        }

        query_final.sort_unstable_by_key(|x| x.1);
        query_final
    }

    /// Se recebi um valor para ser usado como a quantidade de sobreposição mínima,
    /// calculo quantos tokens a query final deve compartilhar com cada documento.
    /// Desconto a quantidade de tokens já removidos por serem muito frequentes
    fn calcular_min_overlap(
        query_len: usize,
        query_final_len: usize,
        sobreposicao_min: Option<f32>,
    ) -> Contagem {
        let n_tokens_removidos = query_len - query_final_len;

        sobreposicao_min
            .map(|sobreposicao| {
                ((sobreposicao * query_len as f32 - n_tokens_removidos as f32).ceil() as Contagem)
                    .clamp(1, Contagem::MAX) // Forço esse valor ser no mínimo 1, para não degenerar para um seq scan
            })
            .unwrap_or(0)
    }

    /// Calculo da quantidade de tokens em comum com a query para cada documento,
    /// excluindo os casos que já não vão bater com a meta de overlap mínimo.
    fn acumular_contagens(
        &self,
        query_final: &[(Token, Contagem)],
        tam_query: Contagem,
        min_overlap: Contagem,
        resultado: &mut SearchIterator<'_>,
    ) {
        for (i, (token, _)) in query_final.iter().enumerate() {
            let ngrams_restantes = tam_query - i as Contagem;

            if let Some(documentos) = self.buckets.get(token) {
                for doc in documentos {
                    let cont = &mut resultado.contagem[*doc as usize];

                    if *cont == 0 {
                        if ngrams_restantes >= min_overlap {
                            *cont = 1;
                            resultado.ativos.push(*doc);
                        }
                    } else if *cont + ngrams_restantes >= min_overlap {
                        *cont = cont.saturating_add(1);
                    } else {
                        *cont = 0;
                    }
                }
            }
        }
    }

    pub fn buscar(
        &self,
        query: &[Token],
        sobreposicao_min: Option<f32>,
        max_df_freq: Option<f32>,
    ) -> SearchIterator<'_> {
        let tam_query = query.len() as Contagem;

        if tam_query == 0 {
            return SearchIterator::vazio();
        }

        let max_freq_aceitavel = self.max_freq_aceitavel(max_df_freq);

        let query_final = self.preparar_query(query, max_freq_aceitavel);

        let min_overlap =
            Self::calcular_min_overlap(query.len(), query_final.len(), sobreposicao_min);

        // Calculo da quantidade de tokens em comum com a query para cada documento,
        // excluindo os casos que já não vão bater com a meta de overlap mínimo.
        let mut resultado = SearchIterator::new(min_overlap, self.total_docs(), &self.docs);
        self.acumular_contagens(&query_final, tam_query, min_overlap, &mut resultado);

        resultado
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::busca_fuzzy::tokenizer::Token;

    fn t(v: u32) -> Token {
        v as Token
    }

    fn build_index(docs: &[(Doc, &[u32])]) -> InvertedIndex {
        let mut idx = InvertedIndex::default();

        for (doc, tokens) in docs {
            let tokens: Vec<Token> = tokens.iter().map(|x| *x as Token).collect();
            idx.add(&tokens, *doc);
        }

        idx.finalizar();
        idx
    }

    #[test]
    fn buscar_query_vazia() {
        let idx = build_index(&[(1, &[1, 2])]);

        let mut it = idx.buscar(&[], None, None);

        assert_eq!(it.next(), None);
    }

    #[test]
    fn buscar_token_inexistente() {
        let idx = build_index(&[(1, &[1, 2]), (2, &[2, 3])]);

        let mut it = idx.buscar(&[t(999)], None, None);

        assert_eq!(it.next(), None);
    }

    #[test]
    fn buscar_match_simples() {
        let idx = build_index(&[(10, &[1, 2, 3]), (20, &[4, 5])]);

        let mut it = idx.buscar(&[t(1)], None, None);

        assert_eq!(it.next(), Some(10));
        assert_eq!(it.next(), None);
    }

    #[test]
    fn buscar_respeita_min_overlap() {
        let idx = build_index(&[(1, &[1, 2]), (2, &[3]), (3, &[4])]);

        // query tem 4 tokens, logo precisa de 2 matches.
        let mut it = idx.buscar(&[t(1), t(2), t(3), t(4)], Some(0.5), None);

        assert_eq!(it.next(), Some(1));
        assert_eq!(it.next(), None);
    }

    #[test]
    fn buscar_respeita_min_overlap_e_max_df() {
        let idx = build_index(&[(1, &[1, 2]), (2, &[1, 3]), (3, &[1, 5])]);

        // query tem 4 tokens, onde 1 deles é muito comum,
        // logo cada documento precisa ter pelo menos um outro token.
        let mut it = idx.buscar(&[t(1), t(2), t(3), t(4)], Some(0.5), Some(0.5));

        assert_eq!(it.next(), Some(1));
        assert_eq!(it.next(), Some(2));
        assert_eq!(it.next(), None);
    }

    #[test]
    fn buscar_query_toda_filtrada_por_df() {
        // token 1 aparece em todos
        let idx = build_index(&[(1, &[1]), (2, &[1]), (3, &[1])]);

        // Mesmo filtrando, fallback deve permitir match
        let it = idx.buscar(&[t(1)], None, Some(0.5));
        let res: Vec<Doc> = it.collect();

        assert_eq!(res.len(), 3);
    }

    #[test]
    fn buscar_indice_vazio() {
        let idx = InvertedIndex::default();

        let mut it = idx.buscar(&[t(1)], None, None);

        assert_eq!(it.next(), None);
    }

    // Testes de funções secundárias

    #[test]
    fn max_freq_sem_limite() {
        let idx = build_index(&[(1, &[1]), (2, &[2])]);
        let max = idx.max_freq_aceitavel(None);
        assert_eq!(max, Contagem::MAX);
    }

    #[test]
    fn max_freq_com_limite() {
        let idx = build_index(&[(1, &[1]), (2, &[2]), (3, &[3]), (4, &[4])]);

        // 4 docs * 0.5 = 2
        let max = idx.max_freq_aceitavel(Some(0.5));
        assert_eq!(max, 2);
    }

    #[test]
    fn preparar_query_remove_tokens_frequentes() {
        let idx = build_index(&[(1, &[1, 2]), (2, &[1, 3]), (3, &[1, 4])]);

        let max_freq = 2; // token 1 tem freq 3 → deve sair
        let q = idx.preparar_query(&[t(1), t(2), t(3), t(4)], max_freq);
        let tokens: Vec<Token> = q.into_iter().map(|x| x.0).collect();
        assert_eq!(tokens, vec![t(2), t(3), t(4)]);
    }

    #[test]
    fn preparar_query_fallback_query_curta() {
        let idx = build_index(&[(1, &[1]), (2, &[1]), (3, &[1])]);

        let max_freq = 1; // filtraria tudo

        let q = idx.preparar_query(&[t(1), t(9)], max_freq);

        // fallback deve restaurar tamanho original
        assert_eq!(q.len(), 2);
    }

    #[test]
    fn calcular_min_overlap_sem_parametro() {
        let m = InvertedIndex::calcular_min_overlap(4, 4, None);
        assert_eq!(m, 0);
    }

    #[test]
    fn calcular_min_overlap_desconta_removidos() {
        // query original = 4
        // query final = 2 → removeu 2
        // 0.5 * 4 = 2 → 2 - 2 = 0 → clamp → 1
        let m = InvertedIndex::calcular_min_overlap(4, 2, Some(0.5));

        assert_eq!(m, 1);
    }
}
