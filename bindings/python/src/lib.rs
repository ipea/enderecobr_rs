//! Bindings em Rust (`pyo3`) do `enderecobr_rs`.
//!
//! As docstrings públicas — as mesmas que aparecem em `help()` — ficam nos
//! comentários de documentação (`///`) junto de cada item. O stub
//! `enderecobr.pyi` guarda só as assinaturas e tipos, para verificadores
//! estáticos e IDEs.

mod endereco;
mod extenso;
mod padronizador;
mod segmento;
mod separador;
mod texto;

use pyo3::exceptions::PyRuntimeError;
use pyo3::prelude::*;

/// Converte as falhas de resolução/download do modelo em erro Python.
fn erro_de_modelo(erro: String) -> PyErr {
    PyRuntimeError::new_err(format!("Não foi possível obter o modelo: {erro}"))
}

/// Converte a falha de carga do modelo padrão em erro Python.
fn erro_de_modelo_padrao(erro: String) -> PyErr {
    PyRuntimeError::new_err(format!("Não foi possível carregar o modelo padrão: {erro}"))
}

/// Módulo `enderecobr`: padronização e estruturação de endereços brasileiros.
///
/// Implementado em Rust; a docstring de cada item vem do comentário de
/// documentação correspondente.
#[pymodule]
pub mod enderecobr {
    #[pymodule_export]
    use crate::endereco::Endereco;

    #[pymodule_export]
    use crate::extenso::{
        numero_por_extenso, padronizar_numero_romano_por_extenso, padronizar_numeros_por_extenso,
        romano_para_inteiro,
    };

    #[pymodule_export]
    use crate::padronizador::{
        obter_padronizador_bairros, obter_padronizador_complementos,
        obter_padronizador_logradouros, obter_padronizador_numeros,
        obter_padronizador_tipos_logradouros, IdentificadorPadroes, Padronizador,
    };

    #[pymodule_export]
    use crate::segmento::{EnderecoSegmentado, SegmentoEndereco, TipoSegmento};

    #[pymodule_export]
    use crate::separador::{
        estruturar_endereco, obter_caminho_modelo, obter_modelo, segmentar_endereco,
        segmentar_enderecos, SeparadorEndereco,
    };

    #[pymodule_export]
    use crate::texto::{
        is_dado_faltante, metaphone, normalizar, padronizar_bairros, padronizar_cep,
        padronizar_cep_leniente, padronizar_cep_numerico, padronizar_complementos,
        padronizar_estados_para_codigo, padronizar_estados_para_nome,
        padronizar_estados_para_sigla, padronizar_logradouros, padronizar_municipios,
        padronizar_numeros, padronizar_numeros_para_int, padronizar_numeros_para_string,
        padronizar_tipo_logradouro,
    };
}

#[cfg(test)]
mod testes {
    use crate::segmento::TipoSegmento;
    use enderecobr_rs::separador_endereco::TipoSegmento as TipoSegmentoRs;

    #[test]
    fn tipo_segmento_espelha_o_rust() {
        // Mesma quantidade, mesma ordem (a ordem vira o valor inteiro no Python)
        // e sem duas variantes do Rust caindo na mesma variante do Python.
        assert_eq!(TipoSegmento::NOMES.len(), TipoSegmentoRs::TODOS.len());
        for (indice, tipo) in TipoSegmentoRs::TODOS.into_iter().enumerate() {
            let espelho = TipoSegmento::from(tipo);
            assert_eq!(
                espelho as isize, indice as isize,
                "ordem divergente: {tipo}"
            );
            assert_eq!(TipoSegmentoRs::from(espelho), tipo, "ida e volta: {tipo}");
            // O `name` do Python é o nome da variante, como em `enum.IntEnum`.
            assert_eq!(
                TipoSegmento::NOMES[indice],
                format!("{tipo:?}"),
                "nome divergente: {tipo}"
            );
        }
    }
}
