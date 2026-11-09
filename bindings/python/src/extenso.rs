//! Números por extenso e numerais romanos.

use pyo3::prelude::*;

/// Converte sequências de dígitos em uma string para seus equivalentes por extenso em português.
///
/// A função percorre a string de entrada e, ao encontrar números inteiros (em formato ASCII),
/// os substitui pelo nome completo do número (ex: "2" → "dois"), utilizando a função `numero_por_extenso`.
///
/// Parameters
/// ----------
/// valor : str
///     String de entrada que pode conter dígitos a serem convertidos.
///
/// Returns
/// -------
/// str
///     Nova string com dígitos convertidos por extenso. Retorna a string original se não houver dígitos.
///
/// Notes
/// -----
/// - Números muito grandes ou inválidos (ex: overflow no parse para `i32`) são deixados inalterados.
/// - Não trata números negativos ou decimais.
/// - Se a string de entrada não contém nenhum dígito ASCII, retorna a string original.
///
/// Examples
/// --------
/// >>> enderecobr.padronizar_numeros_por_extenso("RUA 2")
/// 'RUA DOIS'
/// >>> enderecobr.padronizar_numeros_por_extenso("RUA -2")
/// 'RUA -DOIS'
/// >>> enderecobr.padronizar_numeros_por_extenso("RUA -2.2")
/// 'RUA -DOIS.DOIS'
/// >>> enderecobr.padronizar_numeros_por_extenso("Sem números")
/// 'Sem números'
#[pyfunction]
pub fn padronizar_numeros_por_extenso(valor: &str) -> String {
    enderecobr_rs::numero_extenso::padronizar_numeros_por_extenso(valor).to_string()
}

/// Substitui números romanos em um texto por suas representações por extenso (em palavras).
/// Apenas sequências que formam números romanos válidos (1–3999) são convertidas.
///
/// Parameters
/// ----------
/// valor : str
///     Texto contendo números romanos a serem convertidos.
///
/// Returns
/// -------
/// str
///     Texto com números romanos substituídos por suas formas por extenso (maiúsculas).
///     Retorna o texto original se nenhuma substituição for necessária.
///
/// Examples
/// --------
/// >>> enderecobr.padronizar_numero_romano_por_extenso("Capítulo IX")
/// 'Capítulo NOVE'
///
/// >>> enderecobr.padronizar_numero_romano_por_extenso("Séculos XV e XX")
/// 'Séculos QUINZE e VINTE'
///
/// >>> enderecobr.padronizar_numero_romano_por_extenso("Rei João VI e Papa Bento XVI")
/// 'Rei João SEIS e Papa Bento DEZESSEIS'
#[pyfunction]
pub fn padronizar_numero_romano_por_extenso(valor: &str) -> String {
    enderecobr_rs::numero_extenso::padronizar_numero_romano_por_extenso(valor).to_string()
}

/// Converte um número inteiro para sua representação por extenso em português.
///
/// Retorna uma string com o número por extenso em letras maiúsculas.
///
/// Parameters
/// ----------
/// n : int
///     Número inteiro a ser convertido.
///
/// Returns
/// -------
/// str
///     Representação por extenso do número em português.
///
/// Examples
/// --------
/// >>> enderecobr.numero_por_extenso(0)
/// 'ZERO'
/// >>> enderecobr.numero_por_extenso(42)
/// 'QUARENTA E DOIS'
/// >>> enderecobr.numero_por_extenso(-1500)
/// 'MENOS MIL E QUINHENTOS'
/// >>> enderecobr.numero_por_extenso(2_001_000)
/// 'DOIS MILHOES E MIL'
#[pyfunction]
pub fn numero_por_extenso(n: i32) -> String {
    enderecobr_rs::numero_extenso::numero_por_extenso(n).to_string()
}

/// Converte um número romano em sua representação por extenso (número inteiro).
///
/// Aceita entradas em maiúsculas ou minúsculas. A conversão segue a regra padrão de números romanos,
/// onde símbolos menores à esquerda de maiores são subtraídos. Suporta valores de 1 a 3999.
///
/// Parameters
/// ----------
/// valor : str
///     String contendo a representação de um número romano (ex: "IX", "MCMXC").
///
/// Returns
/// -------
/// int
///     Valor inteiro correspondente ao número romano. Retorna resultados inesperados se a string
///     contiver caracteres inválidos (não tratados como erro).
///
/// Examples
/// --------
/// >>> enderecobr.romano_para_inteiro("IX")
/// 9
/// >>> enderecobr.romano_para_inteiro("xlII")
/// 42
/// >>> enderecobr.romano_para_inteiro("MCMXC")
/// 1990
/// >>> enderecobr.romano_para_inteiro("mmmcmxcix")
/// 3999
///
/// Notes
/// -----
/// - Caracteres inválidos são tratados como 0 e podem gerar resultados inesperados.
/// - A função não valida a correção gramatical da sequência romana (ex: "IIII" retorna 4).
#[pyfunction]
pub fn romano_para_inteiro(valor: &str) -> i32 {
    enderecobr_rs::numero_extenso::romano_para_inteiro(valor)
}
