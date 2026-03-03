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

    pub fn buscar(
        &self,
        query: &[Token],
        sobreposicao_min: Option<f32>,
        max_df_freq: Option<f32>,
    ) -> SearchIterator<'_> {
        let tam_query = query.len() as Contagem;

        if tam_query == 0 {
            SearchIterator::vazio();
        }

        // Avalia em quantos documentos diferentes o token poderia existir,
        // sem se tornar ruído (ex: RUA no contexto de logradouros).
        let max_freq_aceitavel = if let Some(max_df) = max_df_freq {
            (self.total_docs() as f32 * max_df).ceil() as Contagem
        } else {
            Contagem::MAX
        };

        // Preparo a query final já descartando alguns tokens muito frequentes.
        let mut query_final: Vec<(Token, Contagem)> = query
            .iter()
            .filter_map(|t| {
                let freq = self.frequencia_token(t);
                (freq > 0 && freq < max_freq_aceitavel).then_some((*t, freq))
            })
            .collect();

        // TODO: REVER
        if query_final.len() < 3 {
            query_final = query
                .iter()
                .map(|t| (*t, self.frequencia_token(t)))
                .collect();
        }

        // E ordenando pela quantidade de documentos em que ele aparece, afim de priorizar as
        // contagens.
        query_final.sort_unstable_by_key(|x| x.1);

        // Se recebi um valor para ser usado como a quantidade de sobreposição mínima,
        // calculo quantos tokens a query final deve compartilhar com cada documento.
        // Desconto a quantidade de tokens já removidos por serem muito frequentes
        let n_tokens_removidos = query.len() - query_final.len();

        let min_overlap = if let Some(sobreposicao) = sobreposicao_min {
            ((sobreposicao * query.len() as f32 - n_tokens_removidos as f32).ceil() as Contagem)
                .clamp(1, Contagem::MAX) // Forço esse valor ser no mínimo 1, para não degenerar para um seq scan
        } else {
            0
        };

        // Calculo da quantidade de tokens em comum com a query para cada documento,
        // excluindo os casos que já não vão bater com a meta de overlap mínimo.
        let mut resultado = SearchIterator::new(min_overlap, self.total_docs(), &self.docs);

        for (i, (token, _)) in query_final.iter().enumerate() {
            let ngrams_restantes = tam_query - i as Contagem;

            // Pega os documentos que contem o token da query que está sendo avaliado
            if let Some(documentos) = self.buckets.get(token) {
                for doc in documentos {
                    let cont = &mut resultado.contagem[*doc as usize];

                    // primeira vez que vemos esse doc
                    if *cont == 0 {
                        // Se ainda dá pra bater a meta de ngrams
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

        resultado
    }
}
