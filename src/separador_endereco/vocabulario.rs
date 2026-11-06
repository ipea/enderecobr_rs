//! Vocabulário de termos conhecidos casados sobre um texto já tokenizado.

use std::ops::Range;

use aho_corasick::{AhoCorasick, MatchKind};

use crate::normalizar;

/// Conjunto de termos formados por palavras.
///
/// Serve para achar sequências de palavras conhecidas num texto: com os termos
/// `SANTA RITA DO PASSA QUATRO` e `PASSA QUATRO`, o texto `SANTA RITA DO PASSA
/// QUATRO` casa só o termo longo, porque o casamento é sempre o mais à esquerda
/// e o mais longo possível, sem sobreposição.
///
/// A busca é feita palavra a palavra sobre a saída de [`casar`](Self::casar):
/// a pontuação do texto fica de fora, então `OLHO D'ÁGUA` casa com o termo
/// `OLHO D'AGUA`.
///
/// ```
/// use enderecobr_rs::separador_endereco::vocabulario::Vocabulario;
///
/// let vocabulario = Vocabulario::novo(["BOA VISTA"]);
///
/// let palavras = ["RUA", "BOA", "VISTA", "100"];
/// assert_eq!(vocabulario.casar(&palavras), vec![1..3]);
/// ```
pub struct Vocabulario {
    busca: AhoCorasick,
}

impl Vocabulario {
    /// Compila os termos.
    ///
    /// Cada termo é normalizado e quebrado nas palavras dele, então a grafia
    /// original não importa: `Olho d'Água` é o mesmo termo que `OLHO D AGUA`.
    /// Termo sem nenhuma palavra é ignorado.
    pub fn novo<I, S>(termos: I) -> Self
    where
        I: IntoIterator<Item = S>,
        S: AsRef<str>,
    {
        let padroes: Vec<String> = termos
            .into_iter()
            .map(|termo| chave(termo.as_ref()))
            .filter(|chave| !chave.is_empty())
            .map(|chave| format!(" {chave} "))
            .collect();

        Self {
            busca: AhoCorasick::builder()
                .match_kind(MatchKind::LeftmostLongest)
                .build(&padroes)
                .expect("termo do vocabulário é válido"),
        }
    }

    /// Intervalos das palavras de cada ocorrência, na ordem do texto e sem
    /// sobreposição.
    ///
    /// `palavras` são as palavras do texto já normalizadas e sem pontuação
    /// (`D'Água` entra como `AGUA`), sem espaço nem palavra vazia dentro.
    pub fn casar(&self, palavras: &[&str]) -> Vec<Range<usize>> {
        // Os termos são procurados num texto com dois espaços entre as palavras.
        // Como cada termo começa e termina com um espaço, o casamento só fecha
        // entre palavras (`PEDRA` não casa em `PEDRAS`) e dois termos seguidos
        // ficam com um separador para cada um.
        let mut texto = String::new();
        let mut inicios = Vec::with_capacity(palavras.len());
        for palavra in palavras {
            texto.push_str("  ");
            inicios.push(texto.len());
            texto.push_str(palavra);
        }
        texto.push_str("  ");

        self.busca
            .find_iter(&texto)
            .map(|achado| {
                let inicio = inicios.partition_point(|&posicao| posicao <= achado.start());
                let fim = inicios.partition_point(|&posicao| posicao < achado.end());
                inicio..fim
            })
            .collect()
    }
}

/// Chave de um termo: as palavras dele normalizadas, separadas por dois
/// espaços, a mesma separação usada no texto de busca.
fn chave(termo: &str) -> String {
    let normalizado = normalizar(termo);
    normalizado
        .split(|c: char| !c.is_alphanumeric())
        .filter(|palavra| !palavra.is_empty())
        .collect::<Vec<&str>>()
        .join("  ")
}

#[cfg(test)]
mod tests {
    use super::*;

    fn vocabulario() -> Vocabulario {
        Vocabulario::novo([
            "SANTA RITA",
            "SANTA RITA DO PASSA QUATRO",
            "PASSA QUATRO",
            "OLHO D'AGUA",
        ])
    }

    fn casar(palavras: &[&str]) -> Vec<Range<usize>> {
        vocabulario().casar(palavras)
    }

    #[test]
    fn casa_termo_de_uma_palavra() {
        assert_eq!(casar(&["PASSA", "QUATRO"]), vec![0..2]);
    }

    #[test]
    fn prefere_o_termo_mais_longo_sem_sobrepor() {
        let palavras = ["SANTA", "RITA", "DO", "PASSA", "QUATRO"];
        assert_eq!(casar(&palavras), vec![0..5]);

        // Sem o complemento, o termo curto vale.
        assert_eq!(casar(&["SANTA", "RITA"]), vec![0..2]);
    }

    #[test]
    fn casa_termo_depois_de_palavra_desconhecida() {
        assert_eq!(casar(&["RUA", "SANTA", "RITA", "100"]), vec![1..3]);
    }

    #[test]
    fn casa_termos_seguidos() {
        assert_eq!(
            casar(&["PASSA", "QUATRO", "SANTA", "RITA"]),
            vec![0..2, 2..4]
        );
    }

    #[test]
    fn ignora_pontuacao_do_termo() {
        assert_eq!(casar(&["OLHO", "D", "AGUA"]), vec![0..3]);
    }

    #[test]
    fn nao_casa_dentro_de_palavra_maior() {
        // `PEDRA` não pode casar em `PEDRAS`, que é outra palavra.
        let vocabulario = Vocabulario::novo(["PEDRA", "PEDRA BRANCA"]);
        assert!(vocabulario.casar(&["PEDRAS"]).is_empty());
        assert_eq!(vocabulario.casar(&["PEDRA", "BRANCA"]), vec![0..2]);
        assert_eq!(vocabulario.casar(&["RUA", "PEDRA", "1"]), vec![1..2]);
    }

    #[test]
    fn nao_casa_sem_termo_completo() {
        assert!(casar(&["RUA", "SANTA"]).is_empty());
        assert!(casar(&[]).is_empty());
    }

    #[test]
    fn aceita_vocabulario_vazio_e_termo_repetido() {
        assert!(Vocabulario::novo(Vec::<&str>::new())
            .casar(&["A"])
            .is_empty());
        assert_eq!(
            Vocabulario::novo(["BOA VISTA", "Boa Vista", "."]).casar(&["BOA", "VISTA"]),
            vec![0..2]
        );
    }
}
