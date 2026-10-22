use itertools::Itertools;
use serde::Serialize;

use crate::{
    padronizar_bairros, padronizar_cep_leniente, padronizar_complementos, padronizar_logradouros,
    padronizar_numeros,
};

/// Representa um endereço separado em seus atributos constituintes.
#[derive(Clone, Debug, Default, PartialEq, Serialize)]
pub struct Endereco {
    pub logradouro: Option<String>,
    pub numero: Option<String>,
    pub complemento: Option<String>,
    pub localidade: Option<String>,
    pub cep: Option<String>,
}

/// Serializa o endereço em JSON.
pub fn endereco_como_json(endereco: &Endereco) -> String {
    serde_json::to_string(endereco).unwrap_or_else(|_| "{}".to_string())
}

/// Padroniza todos os campos do endereço no próprio objeto, sem criar outro: cada campo
/// recebe a função adequada — [`padronizar_logradouros`] para o logradouro,
/// [`padronizar_numeros`] para o número, [`padronizar_complementos`] para o complemento,
/// [`padronizar_bairros`] para a localidade e [`padronizar_cep_leniente`] para o CEP.
/// Campos `None` permanecem `None`. Os valores antigos são consumidos (via `take`), então
/// só há alocação para os textos padronizados que substituem os originais.
pub fn padronizar_in_place(endereco: &mut Endereco) {
    endereco.logradouro = endereco
        .logradouro
        .take()
        .map(|x| padronizar_logradouros(x.as_str()));
    endereco.numero = endereco
        .numero
        .take()
        .map(|x| padronizar_numeros(x.as_str()));
    endereco.complemento = endereco
        .complemento
        .take()
        .map(|x| padronizar_complementos(x.as_str()));
    endereco.localidade = endereco
        .localidade
        .take()
        .map(|x| padronizar_bairros(x.as_str()));
    endereco.cep = endereco
        .cep
        .take()
        .map(|x| padronizar_cep_leniente(x.as_str()));
}

/// Obtém uma representação textual simples dos atributos desta struct,
/// separados por vírgula, caso existam.
pub fn formatar(endereco: &Endereco) -> String {
    [
        &endereco.logradouro,
        &endereco.numero,
        &endereco.complemento,
        &endereco.localidade,
    ]
    .iter()
    .filter_map(|opt| opt.as_deref())
    .map(|x| x.trim())
    .join(", ")
}

// Os métodos abaixo são apenas facilitadores para quem consome a crate direto do Rust.
impl Endereco {
    pub fn como_json(&self) -> String {
        endereco_como_json(self)
    }

    pub fn padronizar(&mut self) {
        padronizar_in_place(self)
    }

    pub fn endereco_padronizado(&self) -> Endereco {
        let mut novo = self.clone();
        padronizar_in_place(&mut novo);
        novo
    }

    pub fn formatar(&self) -> String {
        formatar(self)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_endereco_padronizado() {
        assert_eq!(
            Endereco {
                logradouro: Some("R gen. glicerio".to_string()),
                numero: Some("1".to_string()),
                complemento: Some("apt 405".to_string()),
                localidade: Some("jd botanico".to_string()),
                cep: Some("20040020".to_string()), // antes era None
            }
            .endereco_padronizado(),
            Endereco {
                logradouro: Some("RUA GENERAL GLICERIO".to_string()),
                numero: Some("1".to_string()),
                complemento: Some("APARTAMENTO 405".to_string()),
                localidade: Some("JARDIM BOTANICO".to_string()),
                cep: Some("20040-020".to_string()), // antes era None
            }
        )
    }
}
