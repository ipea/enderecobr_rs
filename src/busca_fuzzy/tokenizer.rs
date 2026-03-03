use rustc_hash::FxHashMap;
use serde::{Deserialize, Serialize};

pub type Token = u16;

#[derive(Clone, Serialize, Deserialize)]
pub struct NgramTokenizer {
    pub ngram_size: usize,
    pub token_map: FxHashMap<String, Token>,
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

    pub fn intern(&mut self, s: &str) -> Token {
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
