use clap::Parser;
use enderecobr_rs::separador_endereco::EnderecoSegmentado;
use enderecobr_rs::{
    endereco::Endereco, estruturar_endereco, is_dado_faltante, metaphone::metaphone,
    padronizar_bairros, padronizar_cep, padronizar_cep_leniente, padronizar_complementos,
    padronizar_estados_para_codigo, padronizar_estados_para_nome, padronizar_estados_para_sigla,
    padronizar_logradouros, padronizar_municipios, padronizar_numeros, padronizar_tipo_logradouro,
    segmentar_endereco, OpcoesEndereco, OpcoesSegmentacao,
};
use serde::Serialize;
use std::io::{self, BufRead};

/// Utilitário iterativo para realizar pequenos testes de linha de comando com os padronizadores e
/// demais utilitários desta biblioteca.
#[derive(Parser)]
#[clap(author, version)]
struct Args {
    /// Tipo de padronizador. Aceita: logradouro, logr, tipo_logradouro, tipo_logr, numero, num,
    /// bairro, complemento, comp, estado, estado_nome, estado_codigo, municipio, mun, cep,
    /// cep_leniente, metaphone, dado_faltante, segmentacao, estruturacao, formatacao
    #[arg(value_enum)]
    tipo: String,

    /// Valor a ser padronizado (opcional, lê de stdin iterativamente se ausente)
    valor: Option<String>,
}

fn main() {
    let args = Args::parse();
    let padronizador =
        obter_padronizador_por_tipo(&args.tipo).expect("Tipo de padronizador não localizado.");

    if let Some(v) = args.valor {
        println!("{}", padronizador(&v));
    } else {
        let stdin = io::stdin();
        for line in stdin.lock().lines().map_while(Result::ok) {
            println!("{}", padronizador(&line));
        }
    }
}

/// Seleciona um padronizador a partir do nome aceito na linha de comando.
fn obter_padronizador_por_tipo(tipo: &str) -> Result<fn(&str) -> String, &str> {
    match tipo {
        "logradouro" | "logr" => Ok(padronizar_logradouros),
        "tipo_logradouro" | "tipo_logr" => Ok(padronizar_tipo_logradouro),
        "numero" | "num" => Ok(padronizar_numeros),
        "bairro" => Ok(padronizar_bairros),
        "complemento" | "comp" => Ok(padronizar_complementos),
        "estado" => Ok(|x| padronizar_estados_para_sigla(x).to_string()),
        "estado_nome" => Ok(|x| padronizar_estados_para_nome(x).to_string()),
        "estado_codigo" => Ok(|x| padronizar_estados_para_codigo(x).to_string()),
        "municipio" | "mun" => Ok(padronizar_municipios),
        "cep" => Ok(|cep| padronizar_cep(cep).unwrap_or_else(|_| String::new())),
        "cep_leniente" => Ok(padronizar_cep_leniente),
        "metaphone" => Ok(metaphone),
        "dado_faltante" => Ok(|x| is_dado_faltante(x).to_string()),
        "segmentacao" => Ok(|val| {
            let segmentado = segmentar_endereco(val, &OpcoesSegmentacao::sem_probabilidades())
                .expect("Não foi possível segmentar o endereço");
            segmentos_como_json(&segmentado)
        }),
        "estruturacao" => Ok(|val| {
            let endereco = estruturar_endereco(val, &OpcoesEndereco::default())
                .expect("Não foi possível estruturar o endereço");
            endereco_como_json(&endereco)
        }),
        "formatacao" => Ok(|val| {
            estruturar_endereco(val, &OpcoesEndereco::default())
                .expect("Não foi possível estruturar o endereço")
                .formatar()
        }),
        _ => Err("Nenhum padronizador encontrado"),
    }
}

/// Os campos vazios saem como `null`; as probabilidades, só quando calculadas.
#[derive(Serialize)]
struct EnderecoJson<'a> {
    logradouro: &'a Option<String>,
    numero: &'a Option<String>,
    complemento: &'a Option<String>,
    localidade: &'a Option<String>,
    cep: &'a Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    probabilidade: Option<f64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    confianca: Option<f64>,
}

fn endereco_como_json(endereco: &Endereco) -> String {
    serde_json::to_string(&EnderecoJson {
        logradouro: &endereco.logradouro,
        numero: &endereco.numero,
        complemento: &endereco.complemento,
        localidade: &endereco.localidade,
        cep: &endereco.cep,
        probabilidade: endereco.probabilidade,
        confianca: endereco.confianca,
    })
    .unwrap_or_else(|_| "{}".to_string())
}

/// Uma sessão de segmentação sai como `{"segmentos": [...]}`, com o rótulo de
/// cada tipo em minúsculas.
#[derive(Serialize)]
struct SegmentosJson<'a> {
    segmentos: Vec<SegmentoJson<'a>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    probabilidade: Option<f64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    confianca: Option<f64>,
}

#[derive(Serialize)]
struct SegmentoJson<'a> {
    valor: &'a str,
    tipo: &'static str,
    #[serde(skip_serializing_if = "Option::is_none")]
    probabilidade: Option<f64>,
}

fn segmentos_como_json(segmentado: &EnderecoSegmentado) -> String {
    let segmentos = segmentado
        .segmentos
        .iter()
        .map(|segmento| SegmentoJson {
            valor: &segmento.valor,
            tipo: segmento.tipo.como_str(),
            probabilidade: segmento.probabilidade,
        })
        .collect();

    serde_json::to_string(&SegmentosJson {
        segmentos,
        probabilidade: segmentado.probabilidade,
        confianca: segmentado.confianca,
    })
    .unwrap_or_else(|_| "[]".to_string())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_obter_padronizador_por_tipo() {
        // Logradouro
        assert_eq!(
            obter_padronizador_por_tipo("logradouro").unwrap()("r. gen"),
            "RUA GENERAL"
        );
        assert_eq!(
            obter_padronizador_por_tipo("logr").unwrap()("r. gen"),
            "RUA GENERAL"
        );

        // Tipo de logradouro
        assert_eq!(
            obter_padronizador_por_tipo("tipo_logradouro").unwrap()("R"),
            "RUA"
        );
        assert_eq!(
            obter_padronizador_por_tipo("tipo_logr").unwrap()("AVE"),
            "AVENIDA"
        );

        // Número
        assert_eq!(obter_padronizador_por_tipo("numero").unwrap()("001"), "1");
        assert_eq!(obter_padronizador_por_tipo("num").unwrap()("001"), "1");

        // Bairro
        assert_eq!(
            obter_padronizador_por_tipo("bairro").unwrap()("prq ind"),
            "PARQUE INDUSTRIAL"
        );

        // Complemento
        assert_eq!(
            obter_padronizador_por_tipo("complemento").unwrap()("apto 405"),
            "APARTAMENTO 405"
        );
        assert_eq!(
            obter_padronizador_por_tipo("comp").unwrap()("apto 405"),
            "APARTAMENTO 405"
        );

        // Estado
        assert_eq!(obter_padronizador_por_tipo("estado").unwrap()("rj"), "RJ");
        assert_eq!(
            obter_padronizador_por_tipo("estado_nome").unwrap()("rj"),
            "RIO DE JANEIRO"
        );
        assert_eq!(
            obter_padronizador_por_tipo("estado_codigo").unwrap()("rj"),
            "33"
        );

        // Município
        assert_eq!(
            obter_padronizador_por_tipo("municipio").unwrap()("rio de janeiro"),
            "RIO DE JANEIRO"
        );
        assert_eq!(
            obter_padronizador_por_tipo("mun").unwrap()("rio de janeiro"),
            "RIO DE JANEIRO"
        );

        // CEP
        assert_eq!(
            obter_padronizador_por_tipo("cep").unwrap()("12345-6"),
            "00123-456"
        );
        assert_eq!(
            obter_padronizador_por_tipo("cep_leniente").unwrap()("a123b45  6"),
            "00123-456"
        );

        // CEP inválido retorna string vazia
        assert_eq!(obter_padronizador_por_tipo("cep").unwrap()("999999999"), "");

        // Metaphone
        assert_eq!(
            obter_padronizador_por_tipo("metaphone").unwrap()("João Silva"),
            "JOAO SILVA"
        );

        // Dado faltante
        assert_eq!(
            obter_padronizador_por_tipo("dado_faltante").unwrap()("SI"),
            "true"
        );
        assert_eq!(
            obter_padronizador_por_tipo("dado_faltante").unwrap()("RUA B"),
            "false"
        );
    }

    #[test]
    fn test_obter_padronizador_por_tipo_invalido() {
        assert_eq!(
            obter_padronizador_por_tipo("banana"),
            Err("Nenhum padronizador encontrado")
        );
        assert_eq!(
            obter_padronizador_por_tipo(""),
            Err("Nenhum padronizador encontrado")
        );
    }

    #[test]
    fn test_endereco_como_json() {
        let endereco = Endereco::novo(Some("r gen. glicerio".to_string()), None, None, None, None);
        assert_eq!(
            endereco_como_json(&endereco),
            r#"{"logradouro":"r gen. glicerio","numero":null,"complemento":null,"localidade":null,"cep":null}"#
        );
    }

    #[test]
    fn test_segmentos_como_json_devolve_o_rotulo_do_tipo() {
        let segmentado = segmentar_endereco(
            "av atlantica, 123",
            &OpcoesSegmentacao::sem_probabilidades(),
        )
        .unwrap();

        assert_eq!(
            segmentos_como_json(&segmentado),
            r#"{"segmentos":[{"valor":"av atlantica","tipo":"logradouro"},{"valor":"123","tipo":"numero"}]}"#
        );
    }
}
