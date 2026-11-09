use itertools::Itertools;
use serde::Serialize;

use crate::{
    padronizar_bairros, padronizar_cep_leniente, padronizar_complementos, padronizar_logradouros,
    padronizar_numeros,
};

/// Representa um endereço separado em seus atributos constituintes.
#[derive(Clone, Debug, Default, PartialEq, Serialize)]
pub struct Endereco {
    /// Nome do logradouro (rua, avenida, travessa etc.).
    pub logradouro: Option<String>,
    /// Número do imóvel, padronizado como `S/N` quando não houver.
    pub numero: Option<String>,
    /// Complemento do imóvel (apartamento, bloco, loja etc.).
    pub complemento: Option<String>,
    /// Bairro ou localidade do endereço.
    pub localidade: Option<String>,
    /// CEP no formato `XXXXX-XXX`.
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

/// Junta os campos preenchidos do endereço em um texto só, separados por
/// vírgula, na ordem logradouro, número, complemento, localidade e CEP.
pub fn formatar(endereco: &Endereco) -> String {
    [
        &endereco.logradouro,
        &endereco.numero,
        &endereco.complemento,
        &endereco.localidade,
        &endereco.cep,
    ]
    .iter()
    .filter_map(|opt| opt.as_deref())
    .map(|x| x.trim())
    .join(", ")
}

// Os métodos abaixo são apenas facilitadores para quem consome a crate direto do Rust.
impl Endereco {
    /// Cria um endereço informando os campos que existem, na ordem dos campos
    /// da struct.
    pub fn novo(
        logradouro: Option<String>,
        numero: Option<String>,
        complemento: Option<String>,
        localidade: Option<String>,
        cep: Option<String>,
    ) -> Endereco {
        Endereco {
            logradouro,
            numero,
            complemento,
            localidade,
            cep,
        }
    }

    /// Serializa o endereço em JSON. Equivalente a [`endereco_como_json`].
    pub fn como_json(&self) -> String {
        endereco_como_json(self)
    }

    /// Padroniza todos os campos deste endereço, modificando-o. Equivalente a
    /// [`padronizar_in_place`].
    pub fn padronizar(&mut self) {
        padronizar_in_place(self)
    }

    /// Devolve uma cópia padronizada deste endereço, sem alterar o original.
    pub fn endereco_padronizado(&self) -> Endereco {
        let mut novo = self.clone();
        padronizar_in_place(&mut novo);
        novo
    }

    /// Devolve o endereço como um texto só. Equivalente a [`formatar`].
    pub fn formatar(&self) -> String {
        formatar(self)
    }
}

impl std::fmt::Display for Endereco {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}", self.formatar())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_endereco_padronizado() {
        let original = Endereco {
            logradouro: Some("R gen. glicerio".to_string()),
            numero: Some("1".to_string()),
            complemento: Some("apt 405".to_string()),
            localidade: Some("jd botanico".to_string()),
            cep: Some("20040020".to_string()), // antes era None
        };
        let esperado = Endereco {
            logradouro: Some("RUA GENERAL GLICERIO".to_string()),
            numero: Some("1".to_string()),
            complemento: Some("APARTAMENTO 405".to_string()),
            localidade: Some("JARDIM BOTANICO".to_string()),
            cep: Some("20040-020".to_string()), // antes era None
        };

        assert_eq!(original.endereco_padronizado(), esperado.clone());

        let mut clone = original.clone();
        clone.padronizar();
        assert_eq!(clone, esperado.clone());
    }
    #[test]
    fn test_formatar_endereco() {
        let end = Endereco::novo(
            Some("r gen. glicerio".to_string()),
            Some("1".to_string()),
            None,
            Some("laranjeiras".to_string()),
            None,
        );
        assert_eq!(end.formatar(), "r gen. glicerio, 1, laranjeiras");

        // Invariante
        assert_eq!(formatar(&end), end.formatar());

        // Invariante
        assert_eq!(formatar(&end), format!("{}", end));
    }

    #[test]
    fn test_criar_json_endereco() {
        let end = Endereco {
            logradouro: Some("r gen. glicerio".to_string()),
            ..Default::default()
        };

        assert_eq!(
            endereco_como_json(&end),
            r#"{"logradouro":"r gen. glicerio","numero":null,"complemento":null,"localidade":null,"cep":null}"#.to_string()
        );
        //
        // Invariante
        assert_eq!(end.como_json(), endereco_como_json(&end));
    }
}
