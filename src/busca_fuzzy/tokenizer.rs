use rustc_hash::FxHashMap;
use serde::{Deserialize, Serialize};

pub type Token = u16;

#[derive(Clone, Serialize, Deserialize)]
pub struct NgramTokenizer {
    pub ngram_size: usize,
    token_map: FxHashMap<String, Token>,
}

impl NgramTokenizer {
    pub fn new(ngram_size: usize) -> Self {
        NgramTokenizer {
            ngram_size,
            token_map: FxHashMap::default(),
        }
    }
    pub fn tokenize_search<'a>(&'a self, text: &'a str) -> impl Iterator<Item = Token> + 'a {
        NgramIter::new(text, self.ngram_size).filter_map(|x| self.token_map.get(x).copied())
    }

    pub fn tokenize_index<'a>(&'a mut self, text: &'a str) -> impl Iterator<Item = Token> + 'a {
        NgramIter::new(text, self.ngram_size).map(|x| self.intern(x))
    }

    pub fn shrink_to_fit(&mut self) {
        self.token_map.shrink_to_fit();
    }

    fn intern(&mut self, s: &str) -> Token {
        if let Some(&id) = self.token_map.get(s) {
            return id;
        }

        let id = self.token_map.len() as Token;
        let owned = s.to_owned();

        self.token_map.insert(owned, id);
        id
    }
}

pub struct NgramIter<'a> {
    string: &'a str,
    ultima_pos: usize,
    tam_ngram: usize,
}

impl<'a> NgramIter<'a> {
    fn new(string: &'a str, tam_ngram: usize) -> Self {
        Self {
            string,
            ultima_pos: 0,
            tam_ngram,
        }
    }
}

impl<'a> Iterator for NgramIter<'a> {
    type Item = &'a str;

    fn next(&mut self) -> Option<Self::Item> {
        if self.ultima_pos + self.tam_ngram > self.string.len() {
            return None;
        }

        let start = self.ultima_pos;
        let end = start + self.tam_ngram;
        self.ultima_pos += 1;
        Some(&self.string[start..end])
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn ngram_iter_basico() {
        let grams: Vec<&str> = NgramIter::new("abcd", 3).collect();
        assert_eq!(grams, vec!["abc", "bcd"]);
    }

    #[test]
    fn ngram_iter_texto_curto() {
        let grams: Vec<&str> = NgramIter::new("ab", 3).collect();
        assert!(grams.is_empty());
    }

    #[test]
    fn tokenize_index_interna_tokens_unicos() {
        let mut tok = NgramTokenizer::new(3);

        let t1: Vec<Token> = tok.tokenize_index("abcd").collect();
        let t2: Vec<Token> = tok.tokenize_index("abcd").collect();

        // mesma sequência
        assert_eq!(t1, t2);

        // ids distintos para ngrams distintos
        assert_ne!(t1[0], t1[1]);
    }

    #[test]
    fn tokenize_search_so_retorna_tokens_existentes() {
        let mut tok = NgramTokenizer::new(3);

        // indexa apenas "abc"
        tok.tokenize_index("abc").for_each(drop);

        // busca tem um ngram desconhecido
        let res: Vec<Token> = tok.tokenize_search("abcd").collect();

        // apenas "abc" deve existir
        assert_eq!(res.len(), 1);
    }

    #[test]
    fn tokenize_search_vazio_sem_indexacao() {
        let tok = NgramTokenizer::new(3);

        let res: Vec<Token> = tok.tokenize_search("abcd").collect();
        assert!(res.is_empty());
    }

    #[test]
    fn shrink_to_fit_nao_afeta_resultado() {
        let mut tok = NgramTokenizer::new(3);

        let antes: Vec<Token> = tok.tokenize_index("abcd").collect();
        tok.shrink_to_fit();
        let depois: Vec<Token> = tok.tokenize_search("abcd").collect();

        assert_eq!(antes, depois);
    }
}
