use rustc_hash::FxHashMap;
use serde::{Deserialize, Serialize};

#[derive(Serialize, Deserialize, Default, Clone)]
pub struct StringPool {
    #[serde(with = "serde_bytes")]
    blob: Vec<u8>,

    offsets: Vec<(u32, u32)>,

    #[serde(skip)] // não vale serializar
    pub inverso: FxHashMap<String, u32>,
}

impl StringPool {
    pub fn shrink_to_fit(&mut self) {
        self.blob.shrink_to_fit();
        self.offsets.shrink_to_fit();
        self.inverso.shrink_to_fit();
    }

    pub fn push(&mut self, s: &str) -> u32 {
        if let Some(&id) = self.inverso.get(s) {
            return id;
        }

        let id = self.offsets.len() as u32;

        let start = self.blob.len() as u32;
        let len = s.len() as u32;

        self.blob.extend_from_slice(s.as_bytes());
        self.offsets.push((start, len));

        self.inverso.insert(s.to_string(), id);

        id
    }
    pub fn get(&self, id: u32) -> &str {
        let (start, len) = self.offsets[id as usize];
        unsafe { std::str::from_utf8_unchecked(&self.blob[start as usize..(start + len) as usize]) }
    }
    pub fn get_str(&self, s: &str) -> Option<u32> {
        self.inverso.get(s).copied()
    }
    pub fn popular_inverso(&mut self) {
        self.inverso.clear();
        for (id, _) in self.offsets.iter().enumerate() {
            let s = self.get(id as u32);
            self.inverso.insert(s.to_string(), id as u32);
        }
    }
}
