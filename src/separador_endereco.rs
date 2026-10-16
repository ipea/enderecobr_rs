#![cfg(feature = "experimental")]
//! # Exemplo de uso
//! ```
//! use enderecobr_rs::{Endereco, segmentar_endereco};
//! let endereco_segmentado = segmentar_endereco("av n sra copacabana, 123, apt
//! 301").como_endereco();
//! let endereco_esperado = Endereco { logradouro: Some("av n sra copacabana".to_string()), numero: Some("123".to_string()), complemento: Some("apt 301".to_string()), ..Default::default() };
//! assert_eq!(endereco_segmentado, endereco_esperado);
//!
//! let endereco_padronizado_esperado = Endereco { logradouro: Some("AVENIDA NOSSA SENHORA COPACABANA".to_string()), numero: Some("123".to_string()), complemento: Some("APARTAMENTO 301".to_string()), ..Default::default() };
//! assert_eq!(endereco_segmentado.endereco_padronizado(), endereco_padronizado_esperado);
//! ```
use std::sync::LazyLock;

use crfsuite::{Attribute, Model};

use regex::Regex;
use rustc_hash::FxHashSet;
use serde::Serialize;

use crate::{estado::ESTADOS, Endereco};

use unicode_normalization::UnicodeNormalization;

fn is_pontuacao(word: &str) -> bool {
    word.chars().next().is_some_and(|c| PONTUACAO.contains(&c))
}

pub struct SeparadorEndereco {
    pub model: Model,
    pub extrator: ExtratorFeature,
}

pub struct ExtratorFeature {
    distancias_vizinhaca: Vec<i32>,
    regex_tokenizer: Regex,
}

#[derive(Serialize)]
pub struct SegmentoEndereco {
    pub valor: String,
    pub tipo: String,
}

#[derive(Serialize)]
pub struct EnderecoSegmentado {
    pub endereco: String,
    pub segmentos: Vec<SegmentoEndereco>,
}

impl ExtratorFeature {
    pub fn new(distancias_vizinhaca: Option<Vec<i32>>) -> Self {
        Self {
            distancias_vizinhaca: distancias_vizinhaca.unwrap_or(vec![-2, -1, 1, 2]),
            // \p{L} => caracteres unicode
            // \p{N} => números unicode
            // Parece que tinha diferença entre as implementações devido às regexes
            regex_tokenizer: Regex::new(r"\p{N}+|\p{L}+|[^\s\p{L}\p{N}]").unwrap(),
        }
    }

    pub fn sent2features(&self, text: &str) -> Vec<Vec<String>> {
        let (toks, _) = self.tokenize(text);
        self.tokens2features(&toks)
    }

    pub fn tokens2features(&self, toks: &[String]) -> Vec<Vec<String>> {
        (0..toks.len())
            .map(|i| self._features_posicao(toks, i).into_iter().collect())
            .collect()
    }

    fn _features_posicao(&self, sent: &[String], i: usize) -> Vec<String> {
        let mut feats = vec!["bias".to_string()];
        feats.push(format!(
            "{}_pos",
            (i as f64 / sent.len() as f64 * 4.0) as i32
        ));
        feats.extend(self._features_token(&sent[i], "0"));

        if i == 0 {
            feats.push("BOS".to_string());
        }
        if i == sent.len() - 1 {
            feats.push("EOS".to_string());
        }

        for &distancia in &self.distancias_vizinhaca {
            feats.extend(self._features_vizinhanca(sent, i, distancia));
        }

        feats
    }

    fn _features_token(&self, token: &str, prefixo: &str) -> Vec<String> {
        let mut feats = Vec::new();
        let token_norm: String = normalize(token).trim().to_string();
        feats.push(token_norm.clone());

        let mut tam = token_norm.len();
        let mut feat_tam = if tam >= 10 {
            "10+".to_string()
        } else {
            tam.to_string()
        };
        feats.push(format!("tam:{}", feat_tam));

        if MARCADORES_CONHECIDOS_DF.contains(&token_norm) {
            feats.push("marcador_df".to_string());
        }
        if MARCADORES_CONHECIDOS_PALMAS.contains(&token_norm) {
            feats.push("marcador_palmas".to_string());
        }
        if SIGLAS_ESTADOS.contains(&token_norm) {
            feats.push("sigla_estado".to_string());
        }

        if token_norm.is_empty() {
            feats.push("is_unknown".to_string());
        } else if is_pontuacao(&token_norm) {
            feats.push("is_punct".to_string());
            let t = feats.iter().position(|x| x == &token_norm);
            if let Some(idx) = t {
                feats.remove(idx);
            }
            feats.push(token_norm.chars().next().unwrap().to_string());
        } else if token_norm.bytes().all(|c| c.is_ascii_digit()) {
            let token_sem_zero = token_norm.trim_start_matches('0');
            feats.retain(|x| x != &token_norm);
            feats.push("is_digit".to_string());
            tam = token_sem_zero.len();
            feat_tam = if tam >= 7 {
                "7+".to_string()
            } else {
                tam.to_string()
            };
            feats.push(format!("digit_len:{}", feat_tam));
        } else if token_norm.bytes().all(|c| c.is_ascii_alphanumeric()) {
            feats.push("is_alpha".to_string());
            if token_norm.bytes().any(|c| c.is_ascii_digit()) {
                feats.push("has_digit".to_string());
            }
        } else {
            feats.push("is_unknown".to_string());
        }

        feats
            .into_iter()
            .map(|f| format!("{}:{}", prefixo, f))
            .collect()
    }

    fn _features_vizinhanca(
        &self,
        sent: &[String],
        indice_inicial: usize,
        distancia: i32,
    ) -> Vec<String> {
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

        if posicao_vizinho.is_none() {
            return vec![];
        }

        let pos_viz = posicao_vizinho.unwrap();
        let sinal = if direcao == 1 { "+" } else { "-" };
        let sufixo = format!("{}{}", sinal, distancia.abs());
        let mut feats = self._features_token(&sent[pos_viz], &sufixo);

        if pos_viz != ((indice_inicial as i32) + distancia) as usize {
            if let Some(pa) = posicao_anterior {
                let faixa = &sent[pa.min(pos_viz)..=pa.max(pos_viz)];
                let tem_pontuacao = faixa.iter().any(|t| is_pontuacao(t));
                if tem_pontuacao {
                    feats.push(format!("tem_pontuacao:{}", sufixo));
                }
            }
        }

        feats
    }

    fn _pos_prox_palavra(
        &self,
        sent: &[String],
        indice_inicial: usize,
        direcao: i32,
    ) -> Option<usize> {
        let mut i = indice_inicial as i32 + direcao;
        while i >= 0 && (i as usize) < sent.len() {
            let tok = &sent[i as usize];
            if !tok.is_empty() && tok.chars().all(|c| c.is_alphanumeric()) {
                return Some(i as usize);
            }
            i += direcao;
        }
        None
    }

    // Funções auxiliares de exemplo
    pub fn tokenize(&self, text: &str) -> (Vec<String>, Vec<usize>) {
        self.regex_tokenizer
            .find_iter(text)
            .map(|m| (m.as_str().to_string(), m.start()))
            .unzip()
    }
}

fn normalize(text: &str) -> String {
    if text.is_ascii() {
        return text.to_ascii_uppercase().to_string();
    }
    text.nfkd()
        .filter(|c| c.is_ascii())
        .map(|b| b.to_ascii_uppercase())
        .collect()
}

impl SeparadorEndereco {
    pub fn new() -> Self {
        let modelo_bin = include_bytes!("../scripts/crf/tagger.crf");
        let model = Model::from_memory(modelo_bin).unwrap();

        SeparadorEndereco {
            model,
            extrator: ExtratorFeature::new(None),
        }
    }

    pub fn tokens2attributes(&self, tokens: &[String]) -> Vec<Vec<Attribute>> {
        self.extrator
            .tokens2features(tokens)
            .iter()
            .map(|toks| toks.iter().map(|feat| Attribute::new(feat, 1.0)).collect())
            .collect()
    }

    fn segmentar(
        &self,
        original: &str,
        tokens: &[String],
        tags: &[String],
        offsets: &[usize],
    ) -> Vec<SegmentoEndereco> {
        let mut segmentos = Vec::new();
        for ((tok, tok_tipo), offset) in tokens.iter().zip(tags).zip(offsets) {
            if tok_tipo == "O" {
                continue;
            }

            let Some((bio, tipo)) = tok_tipo.split_once("_") else {
                continue; // Não deveria acontecer
            };

            if bio == "B" {
                let segmento = SegmentoEndereco {
                    valor: tok.to_string(),
                    tipo: tipo.to_string().to_lowercase(),
                };
                segmentos.push(segmento);
            }
            if bio == "I" {
                if let Some(ultimo_segmento) = segmentos.last_mut() {
                    if ultimo_segmento.tipo == tipo.to_lowercase() {
                        if *offset > 0usize
                            && original
                                .chars()
                                .nth(offset - 1)
                                .map(|c| c.is_whitespace())
                                .unwrap_or(false)
                        {
                            ultimo_segmento.valor.push(' ');
                        }
                        ultimo_segmento.valor.push_str(tok);
                    }
                }
            }
        }

        return segmentos;
    }

    fn segmentar_endereco(&self, texto: &str) -> EnderecoSegmentado {
        let mut tagger = self.model.tagger().unwrap();
        let (tokens, offsets) = self.extrator.tokenize(texto);
        let atributos = self.tokens2attributes(&tokens);

        let tags = tagger.tag(&atributos).unwrap();
        EnderecoSegmentado {
            endereco: texto.to_string(),
            segmentos: self.segmentar(texto, &tokens, &tags, &offsets),
        }
    }
}

// Em Rust, a constant é criada durante a compilação, então só posso chamar funções muito restritas
// quando uso `const`. Nesse caso,  como tenho uma construção complexa da struct `Padronizador`,
// tenho que usar static com inicialização Lazy (o LazyLock aqui previne condições de corrida).
static SEPARADOR: LazyLock<SeparadorEndereco> = LazyLock::new(criar_separador);

fn criar_separador() -> SeparadorEndereco {
    SeparadorEndereco::new()
}

pub fn segmentar_endereco(texto: &str) -> EnderecoSegmentado {
    SEPARADOR.segmentar_endereco(texto)
}

impl EnderecoSegmentado {
    pub fn como_json(&self) -> String {
        serde_json::to_string(&self.segmentos).unwrap_or_else(|_| "[]".to_string())
    }
    pub fn como_endereco(&self) -> Endereco {
        let mut res = Endereco::default();
        for (i, seg) in self.segmentos.iter().enumerate() {
            let atributo_opt = match seg.tipo.as_str() {
                "logradouro" if res.logradouro.is_none() => {
                    Some(res.logradouro.get_or_insert_default())
                }
                "numero" => Some(res.numero.get_or_insert_default()),
                "parcela"
                    if i > 0
                        && self
                            .segmentos
                            .get(i - 1)
                            .filter(|anterior| anterior.tipo == "logradouro")
                            .is_some() =>
                {
                    Some(res.logradouro.get_or_insert_default())
                }
                "parcela" => Some(res.complemento.get_or_insert_default()),
                "modificador_numero" => Some(res.numero.get_or_insert_default()),
                "quilometragem_via" if res.numero.is_none() => {
                    Some(res.numero.get_or_insert_default())
                }
                "quilometragem_via" => Some(res.complemento.get_or_insert_default()),
                "complemento" => Some(res.complemento.get_or_insert_default()),
                "localidade" => Some(res.localidade.get_or_insert_default()),
                "cep" => Some(res.cep.get_or_insert_default()),
                _ => None,
            };

            if let Some(atributo) = atributo_opt {
                if !atributo.is_empty() {
                    atributo.push(' ');
                }
                atributo.push_str(seg.valor.as_str());
            }
        }
        return res;
    }
}

// Constantes usadas para criar as features do CRF.

static MARCADORES_CONHECIDOS_DF: LazyLock<FxHashSet<String>> = LazyLock::new(|| {
    FxHashSet::from_iter(
        [
            "SQN", "SQS", "SQNW", "SQSW", "SCLN", "SCLS", "SCN", "SCS", "SGAN", "SGAS", "SEPN",
            "SEPS", "SRTVN", "SRTVS", "SHN", "SHS", "SHIS", "SHIN", "SHLS", "SHLN", "SHCGN",
            "SHCES", "SHCE", "SHTQ", "SMPW", "SAAN", "SAS", "SAUS", "SAUN", "SBS", "SDS", "SDN",
            "SDMC", "SIG", "SIA", "SIBS", "SCES", "SMHN", "SMLN", "SRES", "SRL", "SO", "SOPI",
            "SOFS", "CLN", "CLS", "CLNW", "ADE", "AOS", "AR", "CCSW", "CSG", "CRS", "CSA", "CSB",
            "CSD", "CNB", "CND", "CNG", "CNL", "CNM", "EQ", "EQNM", "EQNO", "EQNP", "EQS", "QI",
            "QE", "QS", "QR", "QN", "QD", "QNM", "QNN", "QNO", "QNP", "QNA", "QNC", "QND", "QNE",
            "QNF", "QNG", "QNH", "QNJ", "QNL", "QMS", "QMSW", "QRC", "QRSW", "QSB", "QSC", "QSE",
            "QRO", "SIND", "SGCV", "SCE",
        ]
        .iter()
        .map(|x| x.to_string()),
    )
});

static MARCADORES_CONHECIDOS_PALMAS: LazyLock<FxHashSet<String>> = LazyLock::new(|| {
    FxHashSet::from_iter(
        [
            "ARSE", "ARSO", "ARNE", "ARNO", "AC", "ACSE", "ACSO", "ACNE", "ACNO", "ACSU", "ACSV",
            "ASR", "AA", "AAF", "AAE", "AAM", "AANE", "AANO", "AASE", "AASO", "AE", "ALC", "AVNE",
            "AVNO", "AVSE", "AVSO", "APM", "HM", "QI", "QD", "QR", "QC", "LO", "NS",
        ]
        .iter()
        .map(|x| x.to_string()),
    )
});

static SIGLAS_ESTADOS: LazyLock<FxHashSet<String>> =
    LazyLock::new(|| FxHashSet::from_iter(ESTADOS.iter().map(|e| e.sigla.to_string())));

static PONTUACAO: LazyLock<FxHashSet<char>> = LazyLock::new(|| {
    FxHashSet::from_iter("!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~¨´°§¶·«»–—…“”‘’".chars())
});

#[cfg(test)]
mod tests {
    use super::*;

    fn token2features(sent: &[&str], i: usize) -> Vec<String> {
        let toks: Vec<String> = sent.iter().map(|s| s.to_string()).collect();
        ExtratorFeature::new(None).tokens2features(&toks)[i].clone()
    }

    fn tokens2features(sent: &[&str]) -> Vec<Vec<String>> {
        let toks: Vec<String> = sent.iter().map(|s| s.to_string()).collect();
        ExtratorFeature::new(None).tokens2features(&toks)
    }

    fn tokenize(sent: &str) -> Vec<String> {
        ExtratorFeature::new(None).tokenize(sent).0
    }

    #[test]
    fn test_normalize_remove_acentos() {
        assert_eq!(normalize("ação"), "ACAO");
    }

    #[test]
    fn test_normalize_maiusculas_e_minusculas() {
        assert_eq!(normalize("ÁbÇ"), "ABC");
    }

    #[test]
    fn test_normalize_sem_acentos_retorna_igual() {
        assert_eq!(normalize("RUA"), "RUA");
    }

    #[test]
    fn test_tokenize_basico() {
        assert_eq!(
            tokenize("Rua das Flores!"),
            vec!["Rua", "das", "Flores", "!"]
        );
        assert_eq!(tokenize("123, teste"), vec!["123", ",", "teste"]);
        assert_eq!(tokenize(""), Vec::<String>::new());
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
        assert!(feats.contains(&"+1:DAS".to_string()));
        assert!(feats.contains(&"+1:is_alpha".to_string()));
        assert!(feats.contains(&"+2:FLORES".to_string()));
        assert!(feats.contains(&"+2:is_alpha".to_string()));
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
        assert!(feats.contains(&"0:digit_len:3".to_string()));
        assert!(feats.contains(&"-1:RUA".to_string()));
        assert!(feats.contains(&"+1:CENTRO".to_string()));
        assert!(feats.contains(&"+1:is_alpha".to_string()));
        assert!(!feats.contains(&"0:123".to_string()));
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
        assert!(feats.contains(&"+1:CENTRO".to_string()));
        assert!(feats.contains(&"+1:is_alpha".to_string()));
        assert!(!feats.contains(&"EOS".to_string()));
    }

    #[test]
    fn test_token2features_com_token_alfanumerico() {
        let feats = token2features(&["Rua", "A1", "Centro"], 1);
        assert!(feats.contains(&"0:A1".to_string()));
        assert!(feats.contains(&"0:is_alpha".to_string()));
        assert!(feats.contains(&"0:has_digit".to_string()));
        assert!(feats.contains(&"0:tam:2".to_string()));
        assert!(feats.contains(&"-1:RUA".to_string()));
        assert!(feats.contains(&"+1:CENTRO".to_string()));
        assert!(!feats.contains(&"BOS".to_string()));
        assert!(!feats.contains(&"EOS".to_string()));
    }

    #[test]
    fn test_token2features_com_pontuacao_entre_palavras() {
        let feats = token2features(&["Rua", ",", "das", "Flores"], 0);
        assert!(feats.contains(&"0:RUA".to_string()));
        assert!(feats.contains(&"+1:DAS".to_string()));
        assert!(feats.contains(&"+2:FLORES".to_string()));
        assert!(feats.contains(&"tem_pontuacao:+1".to_string()));
        assert!(feats.contains(&"BOS".to_string()));
        assert!(!feats.contains(&"EOS".to_string()));
    }

    #[test]
    fn test_token2features_ignora_pontuacoes_sucessivas() {
        let feats = token2features(&["Rua", ",", ".", "Flores"], 0);
        assert!(feats.contains(&"0:RUA".to_string()));
        assert!(feats.contains(&"+1:FLORES".to_string()));
        assert!(feats.contains(&"+1:is_alpha".to_string()));
        assert!(feats.contains(&"tem_pontuacao:+1".to_string()));
        assert!(feats.contains(&"BOS".to_string()));
        assert!(!feats.contains(&"EOS".to_string()));
    }

    #[test]
    fn test_token2features_palavra_longa() {
        let feats = token2features(&["Inconstitucionalissimamente"], 0);
        assert!(feats.contains(&"0:INCONSTITUCIONALISSIMAMENTE".to_string()));
        assert!(feats.contains(&"0:tam:10+".to_string()));
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
        assert!(!feats.contains(&"+1:;".to_string()));
    }

    #[test]
    fn test_token2features_com_token_numerico_longo_zeros() {
        let feats = token2features(&["000000000000012345"], 0);
        assert!(feats.contains(&"0:is_digit".to_string()));
        assert!(feats.contains(&"0:digit_len:5".to_string()));
        assert!(!feats.contains(&"0:123456789".to_string()));
    }

    #[test]
    fn test_token2features_com_token_numerico_longo() {
        let feats = token2features(&["123456789"], 0);
        assert!(feats.contains(&"0:is_digit".to_string()));
        assert!(feats.contains(&"0:digit_len:7+".to_string()));
        assert!(feats.contains(&"BOS".to_string()));
        assert!(feats.contains(&"EOS".to_string()));
        assert!(!feats.contains(&"0:123456789".to_string()));
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
}
