pub fn intersect_sorted(a: &[u32], b: &[u32]) -> Vec<u32> {
    let mut i = 0;
    let mut j = 0;
    let mut out = Vec::with_capacity(a.len().min(b.len()));

    while i < a.len() && j < b.len() {
        match a[i].cmp(&b[j]) {
            std::cmp::Ordering::Less => i += 1,
            std::cmp::Ordering::Greater => j += 1,
            std::cmp::Ordering::Equal => {
                out.push(a[i]);
                i += 1;
                j += 1;
            }
        }
    }
    out
}

#[cfg(test)]
mod tests {
    use super::intersect_sorted;

    #[test]
    fn intersect_basico() {
        let a = [1, 2, 3, 4];
        let b = [3, 4, 5, 6];
        assert_eq!(intersect_sorted(&a, &b), vec![3, 4]);
    }

    #[test]
    fn sem_intersecao() {
        let a = [1, 2];
        let b = [3, 4];
        assert!(intersect_sorted(&a, &b).is_empty());
    }

    #[test]
    fn um_vazio() {
        let a: [u32; 0] = [];
        let b = [1, 2, 3];
        assert!(intersect_sorted(&a, &b).is_empty());
        assert!(intersect_sorted(&b, &a).is_empty());
    }

    #[test]
    fn iguais() {
        let a = [1, 2, 3];
        let b = [1, 2, 3];
        assert_eq!(intersect_sorted(&a, &b), vec![1, 2, 3]);
    }

    #[test]
    fn com_duplicados() {
        let a = [1, 2, 2, 3, 5];
        let b = [2, 2, 4, 5];
        assert_eq!(intersect_sorted(&a, &b), vec![2, 2, 5]);
    }

    #[test]
    fn intersecao_nas_pontas() {
        let a = [1, 3, 5, 7];
        let b = [1, 2, 7];
        assert_eq!(intersect_sorted(&a, &b), vec![1, 7]);
    }
}
