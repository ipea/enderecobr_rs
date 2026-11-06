use std::borrow::Cow;
use std::sync::LazyLock;

use crfsuite::Attribute;
use regex::Regex;
use rustc_hash::FxHashSet;

use self::TipoToken::{Alpha, Desconhecido, Digito, Pontuacao};
use crate::{estado::ESTADOS, normalizar, separador_endereco::vocabulario::Vocabulario};

/// Transforma o texto do endereço nas features que o modelo usa para
/// decidir o tipo de cada trecho.
pub struct ExtratorFeature {
    distancias_vizinhaca: Vec<i32>,
    regex_tokenizer: Regex,
}

#[derive(PartialEq, Clone, Copy)]
enum TipoToken {
    Pontuacao,
    Digito,
    Alpha,
    Desconhecido,
}

struct TokenInfo<'a> {
    normalizado: Cow<'a, str>,
    tam_bucket: u8,
    tipo: TipoToken,
    marcador_df: bool,
    marcador_palmas: bool,
    uf: bool,
}

// `&str` const: varrer ~30 bytes é bem mais barato no hot path do que um
// lookup em `FxHashSet<char>`, e não aloca nada na inicialização.
const PONTUACAO: &str = "!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~¨´°§¶·«»–—…“”‘’";

// Constantes usadas para criar as features do CRF. Como são consultadas por
// texto já normalizado (emprestado), `&'static str` evita as `String` da
// inicialização sem mudar o custo do lookup (o hash é do conteúdo).

static MARCADORES_CONHECIDOS_DF: LazyLock<FxHashSet<&'static str>> = LazyLock::new(|| {
    FxHashSet::from_iter([
        "SQN", "SQS", "SQNW", "SQSW", "SCLN", "SCLS", "SCN", "SCS", "SGAN", "SGAS", "SEPN", "SEPS",
        "SRTVN", "SRTVS", "SHN", "SHS", "SHIS", "SHIN", "SHLS", "SHLN", "SHCGN", "SHCES", "SHCE",
        "SHTQ", "SMPW", "SAAN", "SAS", "SAUS", "SAUN", "SBS", "SDS", "SDN", "SDMC", "SIG", "SIA",
        "SIBS", "SCES", "SMHN", "SMLN", "SRES", "SRL", "SO", "SOPI", "SOFS", "CLN", "CLS", "CLNW",
        "ADE", "AOS", "AR", "CCSW", "CSG", "CRS", "CSA", "CSB", "CSD", "CNB", "CND", "CNG", "CNL",
        "CNM", "EQ", "EQNM", "EQNO", "EQNP", "EQS", "QI", "QE", "QS", "QR", "QN", "QD", "QNM",
        "QNN", "QNO", "QNP", "QNA", "QNC", "QND", "QNE", "QNF", "QNG", "QNH", "QNJ", "QNL", "QMS",
        "QMSW", "QRC", "QRSW", "QSB", "QSC", "QSE", "QRO", "SIND", "SGCV", "SCE",
    ])
});

static MARCADORES_CONHECIDOS_PALMAS: LazyLock<FxHashSet<&'static str>> = LazyLock::new(|| {
    FxHashSet::from_iter([
        "ARSE", "ARSO", "ARNE", "ARNO", "AC", "ACSE", "ACSO", "ACNE", "ACNO", "ACSU", "ACSV",
        "ASR", "AA", "AAF", "AAE", "AAM", "AANE", "AANO", "AASE", "AASO", "AE", "ALC", "AVNE",
        "AVNO", "AVSE", "AVSO", "APM", "HM", "QI", "QD", "QR", "QC", "LO", "NS",
    ])
});

static SIGLAS_ESTADOS: LazyLock<FxHashSet<&'static str>> =
    LazyLock::new(|| FxHashSet::from_iter(ESTADOS.iter().map(|e| e.sigla)));

// ===== Vocabulários de nomes conhecidos =====

/// Acima de tantos municípios usando o nome como localidade, o nome deixa de ser
/// evidência de município: `BOA VISTA` (1492) é nome de bairro em qualquer
/// lugar, `ANAPOLIS` (2) não. O limiar veio da curva de cobertura × falso-positivo
/// no dataset anotado.
const LIMIAR_AMBIGUIDADE: u32 = 5;

/// Quantos municípios têm uma localidade com o nome de cada município
/// (`cod_ibge,municipio,n_localidades`; 0 = nome que nunca é localidade).
static MUNICIPIOS_AMBIGUIDADE: &str = include_str!("../data/municipios_ambiguidade.csv");

/// Cabeças de núcleo rural. A lista veio do dataset anotado (pureza da etiqueta
/// quando o token abre um nome) e do CNEFE (frequência nacional e quanto o nome
/// também é usado como tipo de via). `LINHA`, `RAMAL`, `VILA`, `GLEBA`,
/// `PARQUE`, `LOTEAMENTO` e `GRANJA` ficaram de fora: são mais tipo de via ou
/// nome de município do que núcleo.
const NUCLEOS_RURAIS: &[&str] = &[
    "COMUNIDADE",
    "POVOADO",
    "FAZENDA",
    "FAZ",
    "SITIO",
    "SIT",
    "ALDEIA",
    "COLONIA",
    "CHACARA",
    "ESTANCIA",
    "ASSENTAMENTO",
    "AGROVILA",
    "LUGAREJO",
    "VILAREJO",
    "ACAMPAMENTO",
    "NUCLEO RURAL",
    "TERRA INDIGENA",
];

/// Vocabulários conhecidos, montados uma única vez.
///
/// Para criar um vocabulário novo, basta um par aqui e um valor em
/// [`TipoVocabulario`]: os tokens dos termos casados passam a sair com as
/// features `0:{prefixo}_B` e `0:{prefixo}_I`.
static VOCABULARIOS: LazyLock<Vec<(TipoVocabulario, Vocabulario)>> =
    LazyLock::new(montar_vocabularios);

fn montar_vocabularios() -> Vec<(TipoVocabulario, Vocabulario)> {
    let mut unicos: Vec<&str> = Vec::new();
    let mut ambiguos: Vec<&str> = Vec::new();
    for linha in MUNICIPIOS_AMBIGUIDADE.lines().skip(1) {
        let mut colunas = linha.split(',');
        let (Some(_codigo), Some(nome), Some(n_localidades)) =
            (colunas.next(), colunas.next(), colunas.next())
        else {
            continue;
        };
        let ambiguo = n_localidades
            .parse::<u32>()
            .is_ok_and(|n| n > LIMIAR_AMBIGUIDADE);
        if ambiguo {
            ambiguos.push(nome);
        } else {
            unicos.push(nome);
        }
    }

    vec![
        (TipoVocabulario::MunicipioUnico, Vocabulario::novo(unicos)),
        (
            TipoVocabulario::MunicipioAmbiguo,
            Vocabulario::novo(ambiguos),
        ),
        (
            TipoVocabulario::NucleoRural,
            Vocabulario::novo(NUCLEOS_RURAIS),
        ),
    ]
}

/// Vocabulário conhecido, que vira feature de léxico.
#[derive(Clone, Copy)]
enum TipoVocabulario {
    /// Nome que praticamente só aparece como município.
    MunicipioUnico,
    /// Nome que também é nome de localidade em muitos municípios.
    MunicipioAmbiguo,
    /// Cabeça de núcleo rural: `POVOADO`, `SITIO`, `AGROVILA`.
    NucleoRural,
}

impl TipoVocabulario {
    /// Prefixo da feature, igual ao da implementação de referência em Python.
    const fn prefixo(self) -> &'static str {
        match self {
            TipoVocabulario::MunicipioUnico => "municipio_unico",
            TipoVocabulario::MunicipioAmbiguo => "municipio_ambiguo",
            TipoVocabulario::NucleoRural => "nucleo",
        }
    }
}

/// Posição da palavra dentro do termo casado, no esquema BIO do modelo.
#[derive(Clone, Copy)]
enum Marca {
    /// Abre o termo.
    Inicio,
    /// Continua um termo de várias palavras.
    Continuacao,
}

impl Marca {
    const fn sufixo(self) -> &'static str {
        match self {
            Marca::Inicio => "B",
            Marca::Continuacao => "I",
        }
    }
}

/// Marca, por palavra, os termos conhecidos que ela compõe.
///
/// Fica por palavra e não por token porque o casamento ignora a pontuação:
/// `OLHO`, `'`, `AGUA` são um termo de duas palavras.
fn marcar_palavras(palavras: &[&str]) -> Vec<Vec<(TipoVocabulario, Marca)>> {
    let mut marcas = vec![Vec::new(); palavras.len()];
    for (tipo, vocabulario) in VOCABULARIOS.iter() {
        for faixa in vocabulario.casar(palavras) {
            let Some(marcas_das_palavras) = marcas.get_mut(faixa) else {
                continue;
            };
            for (posicao, marcas_da_palavra) in marcas_das_palavras.iter_mut().enumerate() {
                let marca = if posicao == 0 {
                    Marca::Inicio
                } else {
                    Marca::Continuacao
                };
                marcas_da_palavra.push((*tipo, marca));
            }
        }
    }
    marcas
}

fn is_pontuacao(word: &str) -> bool {
    word.chars().next().is_some_and(|c| PONTUACAO.contains(c))
}

impl ExtratorFeature {
    /// Cria um extrator. `distancias_vizinhaca` define quais tokens vizinhos
    /// entram como contexto (por padrão, os dois anteriores e os dois seguintes).
    pub fn new(distancias_vizinhaca: Option<Vec<i32>>) -> Self {
        Self {
            distancias_vizinhaca: distancias_vizinhaca.unwrap_or(vec![-2, -1, 1, 2]),
            // \p{L} => caracteres unicode
            // \p{N} => números unicode
            // Parece que tinha diferença entre as implementações devido às regexes
            regex_tokenizer: Regex::new(r"\p{N}+|\p{L}+|[^\s\p{L}\p{N}]")
                .expect("regex do tokenizador é válida"),
        }
    }

    /// Divide o texto em tokens e devolve as features de cada um.
    pub fn sent2features(&self, text: &str) -> Vec<Vec<String>> {
        let (toks, _) = self.tokenize(text);
        self.tokens2features(&toks)
    }

    /// Devolve as features de cada token de uma lista já tokenizada.
    pub fn tokens2features(&self, toks: &[&str]) -> Vec<Vec<String>> {
        self._features(toks)
    }

    /// Features de cada token, convertidas em atributos do CRF.
    pub fn tokens2attributes(&self, tokens: &[&str]) -> Vec<Vec<Attribute>> {
        self._features(tokens)
            .into_iter()
            .map(|feats| feats.into_iter().map(Attribute::from).collect())
            .collect()
    }

    /// Features de todos os tokens, na ordem e já deduplicadas.
    fn _features(&self, toks: &[&str]) -> Vec<Vec<String>> {
        let tok_info: Vec<TokenInfo> = toks.iter().map(|tok| self._token_info(tok)).collect();

        // Palavras que podem casar com o vocabulário, junto do token de origem
        // de cada uma: o casamento ignora a pontuação.
        let mut palavras: Vec<&str> = Vec::new();
        let mut tokens_das_palavras: Vec<usize> = Vec::new();
        for (i, (tok, info)) in toks.iter().zip(&tok_info).enumerate() {
            if tok.chars().all(char::is_alphanumeric) && !info.normalizado.is_empty() {
                palavras.push(info.normalizado.as_ref());
                tokens_das_palavras.push(i);
            }
        }

        let marcas = marcar_palavras(&palavras);

        let mut feats: Vec<Vec<String>> = Vec::with_capacity(toks.len());
        for i in 0..toks.len() {
            let mut feats_token: Vec<String> = Vec::with_capacity(32);
            self._features_posicao(toks, &tok_info, i, &mut feats_token);
            feats.push(feats_token);
        }

        // As marcas são da palavra; a feature de léxico é do token que a contém,
        // como as demais features de posição zero.
        for (palavra, token) in tokens_das_palavras.iter().enumerate() {
            let Some(feats_token) = feats.get_mut(*token) else {
                continue;
            };
            let Some(marcas_da_palavra) = marcas.get(palavra) else {
                continue;
            };
            for (tipo, marca) in marcas_da_palavra {
                feats_token.push(format!("0:{}_{}", tipo.prefixo(), marca.sufixo()));
            }
        }

        for feats_token in &mut feats {
            feats_token.sort_unstable();
            feats_token.dedup();
        }
        feats
    }

    fn _features_posicao(
        &self,
        sent: &[&str],
        tokens_info: &[TokenInfo],
        i: usize,
        feats: &mut Vec<String>,
    ) {
        feats.push("bias".to_string());
        feats.push(format!(
            "{}_pos",
            (i as f64 / sent.len() as f64 * 4.0) as i32
        ));

        let Some(tok_info) = tokens_info.get(i) else {
            return;
        };
        self._token_info_posicional(tok_info, 0, feats);

        if i == 0 {
            feats.push("BOS".to_string());
        }
        if i == sent.len().saturating_sub(1) {
            feats.push("EOS".to_string());
        }

        for &distancia in &self.distancias_vizinhaca {
            self._features_vizinhanca(sent, tokens_info, i, distancia, feats);
        }
    }

    fn _token_info<'a>(&self, token: &'a str) -> TokenInfo<'a> {
        let mut normalizado = normalizar(token);

        // O `all()` de um iterador vazio é `true`, então o token vazio precisa
        // ser tratado antes de tudo (espelha o `if len(token) == 0` do `preproc.py`).
        let tipo = if normalizado.is_empty() {
            Desconhecido
        } else if is_pontuacao(&normalizado) {
            Pontuacao
        } else if normalizado.bytes().all(|c| c.is_ascii_digit()) {
            Digito
        } else if normalizado.bytes().all(|c| c.is_ascii_alphabetic()) {
            Alpha
        } else {
            Desconhecido
        };

        let tam_bucket = if tipo == Digito {
            normalizado.trim_start_matches('0').len().min(10) as u8
        } else {
            normalizado.len().min(10) as u8
        };

        if tipo == Pontuacao {
            normalizado = Cow::Owned(normalizado.chars().take(1).collect());
        }

        // Empresta antes de mover: os campos de bool vêm primeiro,
        // `normalizado` (o move) vem por último. A ordem no literal importa.
        TokenInfo {
            marcador_df: MARCADORES_CONHECIDOS_DF.contains(normalizado.as_ref()),
            marcador_palmas: MARCADORES_CONHECIDOS_PALMAS.contains(normalizado.as_ref()),
            uf: SIGLAS_ESTADOS.contains(normalizado.as_ref()),
            normalizado,
            tam_bucket,
            tipo,
        }
    }

    /// Empilha as features de um token já com o prefixo posicional. Escreve
    /// direto no vetor da posição para não alocar um `Vec` por vizinho.
    fn _token_info_posicional(&self, tok_info: &TokenInfo, pos: i8, res: &mut Vec<String>) {
        res.push(format!("{}:{}", pos, tok_info.normalizado));
        res.push(format!("{}:tam:{}", pos, tok_info.tam_bucket));

        if tok_info.marcador_df {
            res.push(format!("{}:marcador_df", pos));
        }
        if tok_info.marcador_palmas {
            res.push(format!("{}:marcador_palmas", pos));
        }
        if tok_info.uf {
            res.push(format!("{}:sigla_estado", pos));
        }

        let tipo = match tok_info.tipo {
            Alpha => "is_alpha",
            Desconhecido => "is_unknown",
            Pontuacao => "is_punct",
            Digito => "is_digit",
        };
        res.push(format!("{}:{}", pos, tipo));
    }

    fn _features_vizinhanca(
        &self,
        sent: &[&str],
        tokens_info: &[TokenInfo],
        indice_inicial: usize,
        distancia: i32,
        feats: &mut Vec<String>,
    ) {
        assert!(distancia != 0);

        let direcao = if distancia > 0 { 1 } else { -1 };
        let mut posicao_vizinho: Option<usize> = Some(indice_inicial);
        let mut posicao_anterior: Option<usize> = None;

        for _ in 0..distancia.abs() {
            if let Some(pv) = posicao_vizinho {
                posicao_anterior = Some(pv);
                posicao_vizinho = self._pos_prox_palavra(sent, pv, direcao);
            }
        }

        let Some(pos_viz) = posicao_vizinho else {
            return;
        };
        let Some(tok_viz) = tokens_info.get(pos_viz) else {
            return;
        };
        self._token_info_posicional(tok_viz, distancia as i8, feats);

        // A posição geométrica esperada só difere da encontrada quando o
        // vizinho foi alcançado pulando pontuação.
        let posicao_esperada = usize::try_from(indice_inicial as i64 + i64::from(distancia)).ok();
        if posicao_esperada != Some(pos_viz) {
            if let Some(pa) = posicao_anterior {
                let (inicio, fim) = (pa.min(pos_viz), pa.max(pos_viz));
                let tem_pontuacao = sent
                    .get(inicio..=fim)
                    .is_some_and(|faixa| faixa.iter().any(|t| is_pontuacao(t)));
                if tem_pontuacao {
                    feats.push(format!("tem_pontuacao:{}", distancia));
                }
            }
        }
    }

    fn _pos_prox_palavra(
        &self,
        sent: &[&str],
        indice_inicial: usize,
        direcao: i32,
    ) -> Option<usize> {
        let mut i = indice_inicial as i64 + i64::from(direcao);
        loop {
            // Sai pelo `?` assim que o índice passa de qualquer um dos limites
            // (negativo na direção para trás, `sent.len()` na para frente).
            let idx = usize::try_from(i).ok()?;
            let tok = sent.get(idx)?;
            if !tok.is_empty() && tok.chars().all(|c| c.is_alphanumeric()) {
                return Some(idx);
            }
            i += i64::from(direcao);
        }
    }

    /// Divide o texto em tokens (palavras, números e pontuação) e devolve,
    /// junto, a posição de cada token no texto original.
    pub fn tokenize<'a>(&self, text: &'a str) -> (Vec<&'a str>, Vec<usize>) {
        self.regex_tokenizer
            .find_iter(text)
            .map(|m| (m.as_str(), m.start()))
            .unzip()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn token2features(sent: &[&str], i: usize) -> Vec<String> {
        ExtratorFeature::new(None).tokens2features(sent)[i].clone()
    }

    fn tokens2features(sent: &[&str]) -> Vec<Vec<String>> {
        ExtratorFeature::new(None).tokens2features(sent)
    }

    fn tokenize(sent: &str) -> Vec<&str> {
        ExtratorFeature::new(None).tokenize(sent).0
    }

    #[test]
    fn test_tokenize_basico() {
        assert_eq!(
            tokenize("Rua das Flores!"),
            vec!["Rua", "das", "Flores", "!"]
        );
        assert_eq!(tokenize("123, teste"), vec!["123", ",", "teste"]);
        assert_eq!(tokenize(""), Vec::<&str>::new());
        assert_eq!(tokenize("A/B"), vec!["A", "/", "B"]);
    }

    #[test]
    fn test_is_pontuacao_casos_basicos() {
        assert!(is_pontuacao(","));
        assert!(is_pontuacao("..."));
        assert!(!is_pontuacao("a"));
        assert!(!is_pontuacao(""));
    }

    #[test]
    fn test_token2features_primeiro_token_basico() {
        let feats = token2features(&["Rua", "das", "Flores"], 0);
        assert!(feats.contains(&"bias".to_string()));
        assert!(feats.contains(&"0_pos".to_string()));
        assert!(feats.contains(&"0:RUA".to_string()));
        assert!(feats.contains(&"0:is_alpha".to_string()));
        assert!(feats.contains(&"0:tam:3".to_string()));
        assert!(feats.contains(&"BOS".to_string()));
        assert!(feats.contains(&"1:DAS".to_string()));
        assert!(feats.contains(&"1:is_alpha".to_string()));
        assert!(feats.contains(&"2:FLORES".to_string()));
        assert!(feats.contains(&"2:is_alpha".to_string()));
        assert!(!feats.contains(&"EOS".to_string()));
    }

    #[test]
    fn test_token2features_token_final() {
        let feats = token2features(&["Rua", "das", "Flores"], 2);
        assert!(feats.contains(&"bias".to_string()));
        assert!(feats.contains(&"EOS".to_string()));
        assert!(feats.contains(&"0:FLORES".to_string()));
        assert!(feats.contains(&"0:is_alpha".to_string()));
        assert!(feats.contains(&"0:tam:6".to_string()));
        assert!(feats.contains(&"-1:DAS".to_string()));
        assert!(feats.contains(&"-1:is_alpha".to_string()));
        assert!(feats.contains(&"-2:RUA".to_string()));
        assert!(feats.contains(&"-2:is_alpha".to_string()));
        assert!(!feats.contains(&"BOS".to_string()));
    }

    #[test]
    fn test_token2features_token_meio_com_digito() {
        let feats = token2features(&["Rua", "123", "Centro"], 1);
        assert!(feats.contains(&"0:is_digit".to_string()));
        assert!(feats.contains(&"0:tam:3".to_string()));
        assert!(feats.contains(&"-1:RUA".to_string()));
        assert!(feats.contains(&"1:CENTRO".to_string()));
        assert!(feats.contains(&"1:is_alpha".to_string()));
        // O token bruto continua entrando; só `digit_len` deixou de existir.
        assert!(feats.contains(&"0:123".to_string()));
        assert!(!feats.iter().any(|f| f.contains("digit_len")));
        assert!(!feats.contains(&"BOS".to_string()));
        assert!(!feats.contains(&"EOS".to_string()));
    }

    #[test]
    fn test_token2features_token_pontuacao() {
        let feats = token2features(&["Rua", ",", "Centro"], 1);
        assert!(feats.contains(&"0:,".to_string()));
        assert!(feats.contains(&"0:is_punct".to_string()));
        assert!(feats.contains(&"-1:RUA".to_string()));
        assert!(feats.contains(&"-1:is_alpha".to_string()));
        assert!(feats.contains(&"1:CENTRO".to_string()));
        assert!(feats.contains(&"1:is_alpha".to_string()));
        assert!(!feats.contains(&"EOS".to_string()));
    }

    #[test]
    fn test_token2features_com_token_alfanumerico() {
        // O tokenizador separa letras de números, então um token alfanumérico
        // não passa de um caso desconhecido (mesma regra do `preproc.py`).
        let feats = token2features(&["Rua", "A1", "Centro"], 1);
        assert!(feats.contains(&"0:A1".to_string()));
        assert!(feats.contains(&"0:is_unknown".to_string()));
        assert!(!feats.contains(&"0:is_alpha".to_string()));
        assert!(feats.contains(&"0:tam:2".to_string()));
        assert!(feats.contains(&"-1:RUA".to_string()));
        assert!(feats.contains(&"1:CENTRO".to_string()));
        assert!(!feats.contains(&"BOS".to_string()));
        assert!(!feats.contains(&"EOS".to_string()));
    }

    #[test]
    fn test_token2features_com_pontuacao_entre_palavras() {
        let feats = token2features(&["Rua", ",", "das", "Flores"], 0);
        assert!(feats.contains(&"0:RUA".to_string()));
        assert!(feats.contains(&"1:DAS".to_string()));
        assert!(feats.contains(&"2:FLORES".to_string()));
        assert!(feats.contains(&"tem_pontuacao:1".to_string()));
        assert!(feats.contains(&"BOS".to_string()));
        assert!(!feats.contains(&"EOS".to_string()));
    }

    #[test]
    fn test_token2features_ignora_pontuacoes_sucessivas() {
        let feats = token2features(&["Rua", ",", ".", "Flores"], 0);
        assert!(feats.contains(&"0:RUA".to_string()));
        assert!(feats.contains(&"1:FLORES".to_string()));
        assert!(feats.contains(&"1:is_alpha".to_string()));
        assert!(feats.contains(&"tem_pontuacao:1".to_string()));
        assert!(feats.contains(&"BOS".to_string()));
        assert!(!feats.contains(&"EOS".to_string()));
    }

    #[test]
    fn test_token2features_palavra_longa() {
        let feats = token2features(&["Inconstitucionalissimamente"], 0);
        assert!(feats.contains(&"0:INCONSTITUCIONALISSIMAMENTE".to_string()));
        assert!(feats.contains(&"0:tam:10".to_string()));
        assert!(feats.contains(&"0:is_alpha".to_string()));
        assert!(feats.contains(&"BOS".to_string()));
        assert!(feats.contains(&"EOS".to_string()));
        assert!(feats.contains(&"bias".to_string()));
    }

    #[test]
    fn test_token2features_todos_pontuacao() {
        let feats = token2features(&[",", ".", ";"], 1);
        assert!(feats.contains(&"0:is_punct".to_string()));
        assert!(feats.contains(&"0:.".to_string()));
        assert!(feats.contains(&"0:tam:1".to_string()));
        assert!(!feats.contains(&"BOS".to_string()));
        assert!(!feats.contains(&"EOS".to_string()));
        assert!(!feats.contains(&"-1:,".to_string()));
        assert!(!feats.contains(&"1:;".to_string()));
    }

    #[test]
    fn test_token2features_com_token_numerico_longo_zeros() {
        // O `tam` de um dígito usa o comprimento sem zeros à esquerda.
        let feats = token2features(&["000000000000012345"], 0);
        assert!(feats.contains(&"0:is_digit".to_string()));
        assert!(feats.contains(&"0:tam:5".to_string()));
        assert!(feats.contains(&"0:000000000000012345".to_string()));
    }

    #[test]
    fn test_token2features_com_token_numerico_longo() {
        let feats = token2features(&["123456789"], 0);
        assert!(feats.contains(&"0:is_digit".to_string()));
        assert!(feats.contains(&"0:tam:9".to_string()));
        assert!(feats.contains(&"BOS".to_string()));
        assert!(feats.contains(&"EOS".to_string()));
        assert!(feats.contains(&"0:123456789".to_string()));
    }

    #[test]
    fn test_token2features_com_pontuacao_longa() {
        let feats = token2features(&["!!!"], 0);
        assert!(feats.contains(&"0:is_punct".to_string()));
        assert!(feats.contains(&"0:!".to_string()));
        assert!(feats.contains(&"BOS".to_string()));
        assert!(feats.contains(&"EOS".to_string()));
    }

    #[test]
    fn test_token2features_token_vazio() {
        let feats = token2features(&[""], 0);
        assert!(feats.contains(&"0:is_unknown".to_string()));
        assert!(feats.contains(&"BOS".to_string()));
        assert!(feats.contains(&"EOS".to_string()));
        assert!(feats.contains(&"0:tam:0".to_string()));
        assert!(!feats.contains(&"0:is_alpha".to_string()));
    }

    #[test]
    fn test_token2features_token_desconhecido() {
        let feats = token2features(&["😀"], 0);
        assert!(feats.contains(&"0:is_unknown".to_string()));
        assert!(!feats.contains(&"0:😀".to_string()));
        assert!(!feats.contains(&"0:is_alpha".to_string()));
        assert!(feats.contains(&"BOS".to_string()));
        assert!(feats.contains(&"EOS".to_string()));
    }

    #[test]
    fn test_token2features_token_com_acentos() {
        let feats = token2features(&["Árvore"], 0);
        assert!(feats.contains(&"0:ARVORE".to_string()));
        assert!(feats.contains(&"0:is_alpha".to_string()));
        assert!(feats.contains(&"0:tam:6".to_string()));
        assert!(feats.contains(&"BOS".to_string()));
        assert!(feats.contains(&"EOS".to_string()));
        assert!(feats.contains(&"bias".to_string()));
    }

    #[test]
    fn test_tokens2features_lista_basica() {
        let feats = tokens2features(&["Rua", "das"]);
        assert_eq!(feats.len(), 2);
        assert!(feats[0].contains(&"0:RUA".to_string()));
        assert!(feats[1].contains(&"0:DAS".to_string()));
    }

    #[test]
    fn test_tokens2features_contem_bias_em_todos() {
        let feats = tokens2features(&["A", "B", "C"]);
        assert!(feats[0].contains(&"bias".to_string()));
        assert!(feats[1].contains(&"bias".to_string()));
        assert!(feats[2].contains(&"bias".to_string()));
    }

    #[test]
    fn test_tokens2features_sem_duplicatas() {
        let feats = tokens2features(&["Rua", ",", "das", "Flores", "123"]);
        for item in &feats {
            let mut ordenado = item.clone();
            ordenado.sort_unstable();
            ordenado.dedup();
            assert_eq!(ordenado.len(), item.len());
        }
    }

    /// Features de cada token do texto.
    fn features(texto: &str) -> Vec<Vec<String>> {
        ExtratorFeature::new(None).sent2features(texto)
    }

    /// Se o token tem alguma feature com o trecho dado.
    fn tem(feats: &[Vec<String>], i: usize, trecho: &str) -> bool {
        feats
            .get(i)
            .is_some_and(|feats_token| feats_token.iter().any(|feature| feature.contains(trecho)))
    }

    #[test]
    fn municipio_marca_nome_de_varios_tokens() {
        let feats = features("Rua Boa Vista, 100");
        assert!(tem(&feats, 1, "0:municipio_ambiguo_B"));
        assert!(tem(&feats, 2, "0:municipio_ambiguo_I"));
        assert!(!tem(&feats, 0, "municipio"));
        assert!(!tem(&feats, 3, "municipio"));
    }

    #[test]
    fn municipio_inequivoco_nao_usa_feature_de_ambiguo() {
        let feats = features("Anapolis");
        assert!(tem(&feats, 0, "0:municipio_unico_B"));
        assert!(!tem(&feats, 0, "municipio_ambiguo"));
    }

    #[test]
    fn municipio_marca_nome_de_um_token() {
        let feats = features("Rua Colombo, Centro");
        assert!(tem(&feats, 1, "0:municipio_unico_B"));
        assert!(!tem(&feats, 1, "0:municipio_unico_I"));
        // `CENTRO` não é município: a feature não dispara para qualquer palavra.
        assert!(!tem(&feats, 2, "municipio"));
    }

    #[test]
    fn municipio_casa_nome_com_pontuacao_e_acento() {
        let feats = features("Olho d'Água do Borges");
        assert!(tem(&feats, 0, "0:municipio_unico_B"));
        assert!(tem(&feats, 1, "0:municipio_unico_I"));
        assert!(!tem(&feats, 2, "municipio"));
        assert!(tem(&feats, 3, "0:municipio_unico_I"));
        assert!(tem(&feats, 4, "0:municipio_unico_I"));
        assert!(tem(&feats, 5, "0:municipio_unico_I"));
    }

    #[test]
    fn municipio_prefere_o_nome_mais_longo() {
        // `SANTA RITA` e `PASSA QUATRO` também são municípios, mas o nome do
        // logradouro é o composto.
        let feats = features("Santa Rita do Passa Quatro");
        assert!(tem(&feats, 0, "0:municipio_unico_B"));
        assert!(tem(&feats, 4, "0:municipio_unico_I"));
    }

    #[test]
    fn municipio_exige_nome_completo() {
        let feats = features("Rua Sao, 100");
        assert!(!tem(&feats, 1, "municipio"));
    }

    #[test]
    fn nucleo_marca_cabeca_com_nome() {
        let feats = features("Povoado Agua Preta, 65");
        assert!(tem(&feats, 0, "0:nucleo_B"));
        assert!(!tem(&feats, 1, "nucleo"));
    }

    #[test]
    fn nucleo_marca_nome_composto() {
        let feats = features("Nucleo Rural Boa Esperanca");
        assert!(tem(&feats, 0, "0:nucleo_B"));
        assert!(tem(&feats, 1, "0:nucleo_I"));
        assert!(!tem(&feats, 2, "nucleo"));
    }

    #[test]
    fn nucleo_aceita_abreviacao() {
        assert!(tem(&features("Faz Santa Rita"), 0, "0:nucleo_B"));
        assert!(tem(&features("Sit Mirador"), 0, "0:nucleo_B"));
    }

    #[test]
    fn nucleo_marca_a_cabeca_sem_julgar_o_que_vem_depois() {
        // Quem decide se o termo é núcleo, parcela ou ruído é o modelo.
        for texto in ["Chacara 51", "Povoado", "Povoado Sitio", "Estancia SE"] {
            assert!(tem(&features(texto), 0, "0:nucleo_B"), "{texto}");
        }
    }
}
