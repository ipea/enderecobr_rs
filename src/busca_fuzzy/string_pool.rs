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

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_string_pool_empty() {
        let pool = StringPool::default();
        assert_eq!(pool.blob.len(), 0);
        assert_eq!(pool.offsets.len(), 0);
        assert_eq!(pool.inverso.len(), 0);
    }

    #[test]
    fn test_string_pool_push_get_roundtrip() {
        let mut pool = StringPool::default();
        let id1 = pool.push("hello");
        let id2 = pool.push("world");
        let id3 = pool.push("hello"); // duplicado

        assert_eq!(id1, 0);
        assert_eq!(id2, 1);
        assert_eq!(id3, 0); // mesmo ID para string duplicada
        assert_eq!(pool.get(id1), "hello");
        assert_eq!(pool.get(id2), "world");
    }

    #[test]
    fn test_string_pool_get_str_existing() {
        let mut pool = StringPool::default();
        pool.push("test");
        pool.push("rust");

        assert_eq!(pool.get_str("test"), Some(0));
        assert_eq!(pool.get_str("rust"), Some(1));
        assert_eq!(pool.get_str("unknown"), None);
    }

    #[test]
    fn test_string_pool_no_duplicates_in_blob() {
        let mut pool = StringPool::default();
        let id1 = pool.push("abc");
        let id2 = pool.push("abc");

        assert_eq!(id1, id2);
        assert_eq!(pool.offsets.len(), 1);
        assert_eq!(pool.blob.len(), 3);
    }

    #[test]
    fn test_string_pool_push_long_string() {
        let mut pool = StringPool::default();
        let long_str = "a".repeat(1000);
        let id = pool.push(&long_str);

        assert_eq!(pool.get(id), long_str.as_str());
        assert_eq!(pool.blob.len(), 1000);
        assert_eq!(pool.offsets.len(), 1);
    }

    #[test]
    fn test_string_pool_popular_inverso() {
        let mut pool = StringPool::default();
        pool.push("first");
        pool.push("second");
        // inverso está vazio
        assert_eq!(pool.inverso.len(), 2);

        pool.inverso.clear();
        assert_eq!(pool.inverso.len(), 0);

        pool.popular_inverso();
        assert_eq!(pool.inverso.len(), 2);
        assert_eq!(pool.get_str("first"), Some(0));
        assert_eq!(pool.get_str("second"), Some(1));
    }

    #[test]
    fn test_string_pool_shrink_to_fit() {
        let mut pool = StringPool::default();
        pool.push("small");
        pool.inverso.reserve(1000);
        pool.inverso.shrink_to_fit(); // força redução após alocação
        pool.shrink_to_fit();

        let capacity_after = pool.blob.capacity();
        pool.blob.reserve(100);
        pool.shrink_to_fit();
        assert_eq!(pool.blob.capacity(), capacity_after);
    }
}
