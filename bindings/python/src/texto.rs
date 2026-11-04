//! Funções de padronização de texto: cada `#[pyfunction]` só delega para a lib.

use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;

/// Padroniza uma string representando logradouros de municípios brasileiros.
///
/// Realiza uma série de transformações para normalizar nomes de ruas, avenidas e
/// outros tipos de logradouros segundo convenções comuns em bases de endereços no Brasil.
///
/// Parameters
/// ----------
/// valor : str
///     Texto bruto representando um logradouro (ex: 'r. gen.. glicério').
///
/// Returns
/// -------
/// str
///     Texto padronizado em caixa alta, sem acentos, com abreviações expandidas
///     e formatação consistente.
///
/// Examples
/// --------
/// >>> import enderecobr
/// >>> enderecobr.padronizar_logradouros("r. gen.. glicério")
/// 'RUA GENERAL GLICERIO'
///
/// Notes
/// -----
/// As seguintes operações são aplicadas sequencialmente:
///
/// - Remoção de espaços extras no início, fim e entre palavras;
/// - Conversão para maiúsculas;
/// - Remoção de acentos e conversão de caracteres não-ASCII;
/// - Normalização de pontos em abreviações (ex: 'gen..' → 'GEN');
/// - Inserção de espaços após abreviações com pontos (ex: 'R.JOSE' → 'R. JOSE');
/// - Expansão de abreviações comuns (ex: 'R.' → 'RUA', 'AV.' → 'AVENIDA');
/// - Correção de erros ortográficos frequentes (ex: 'GLICERIO' em vez de 'GLICÉRIO').
///
/// As expressões regulares são compiladas na primeira chamada, portanto a primeira
/// execução pode ser mais lenta. Chamadas subsequentes reutilizam as regexes compiladas.
#[pyfunction]
pub fn padronizar_logradouros(valor: &str) -> String {
    enderecobr_rs::padronizar_logradouros(valor)
}

/// Padroniza uma string representando números de logradouros.
///
/// Normaliza números de endereços, removendo formatações inconsistentes e
/// tratando casos especiais como ausência de número (ex: "SN", "S/N", etc).
///
/// Parameters
/// ----------
/// valor : str
///     Texto bruto representando o número de um logradouro (ex: '0210', 'S. N. ').
///
/// Returns
/// -------
/// str
///     Número padronizado. Números comuns têm zeros à esquerda removidos;
///     valores nulos ou variações de "SN" são convertidos para "S/N".
///
/// Examples
/// --------
/// >>> import enderecobr
/// >>> enderecobr.padronizar_numeros("0210")
/// '210'
/// >>> enderecobr.padronizar_numeros("  S. N.  ")
/// 'S/N'
///
/// Notes
/// -----
/// As seguintes operações são aplicadas:
///
/// - Remoção de espaços extras no início, fim e entre caracteres;
/// - Remoção de zeros à esquerda em números;
/// - Detecção e substituição de variações de "sem número" (SN, S N, S./N., etc) por "S/N";
/// - Retorno de string vazia se a entrada for completamente inválida ou nula.
///
/// As expressões regulares são compiladas na primeira chamada, portanto a primeira
/// execução pode ser mais lenta. Chamadas subsequentes reutilizam as regexes compiladas.
#[pyfunction]
pub fn padronizar_numeros(valor: &str) -> String {
    enderecobr_rs::padronizar_numeros(valor)
}

/// Padroniza uma string representando complementos de logradouros.
///
/// Parameters
/// ----------
/// valor : str
///     Texto bruto representando um complemento (ex: 'APTO. 405', 'QD1 LT2 CS3').
///
/// Returns
/// -------
/// str
///     Texto padronizado em caixa alta, sem acentos, com abreviações expandidas
///     e formatação consistente.
///
/// Examples
/// --------
/// >>> import enderecobr
/// >>> enderecobr.padronizar_complementos("QD1 LT2 CS3")
/// 'QUADRA 1 LOTE 2 CASA 3'
/// >>> enderecobr.padronizar_complementos("APTO. 405")
/// 'APARTAMENTO 405'
///
/// Notes
/// -----
/// As seguintes operações são aplicadas:
///
/// - Remoção de espaços extras no início, fim e entre palavras;
/// - Conversão para maiúsculas;
/// - Remoção de acentos e caracteres não ASCII;
/// - Normalização de pontos em abreviações (ex: 'APTO.' → 'APARTAMENTO');
/// - Expansão de abreviações comuns (ex: 'QD' → 'QUADRA', 'LT' → 'LOTE', 'CS' → 'CASA');
/// - Correção de erros ortográficos ou variações comuns.
///
/// As expressões regulares são compiladas na primeira chamada, portanto a primeira
/// execução pode ser mais lenta. Chamadas subsequentes reutilizam as regexes compiladas.
#[pyfunction]
pub fn padronizar_complementos(valor: &str) -> String {
    enderecobr_rs::padronizar_complementos(valor)
}

/// Padroniza uma string representando bairros de municípios brasileiros.
///
/// Examples
/// --------
/// >>> import enderecobr
/// >>> enderecobr.padronizar_bairros("PRQ IND")
/// 'PARQUE INDUSTRIAL'
/// >>> enderecobr.padronizar_bairros("NSA SEN DE FATIMA")
/// 'NOSSA SENHORA DE FATIMA'
/// >>> enderecobr.padronizar_bairros("ILHA DO GOV")
/// 'ILHA DO GOVERNADOR'
///
/// Notes
/// -----
/// Operações realizadas durante a padronização:
///
/// - Remoção de espaços em branco antes, depois e excesso entre palavras;
/// - Conversão para caixa alta;
/// - Remoção de acentos e caracteres não ASCII;
/// - Adição de espaços após abreviações com pontos;
/// - Expansão de abreviações comuns usando expressões regulares;
/// - Correção de pequenos erros ortográficos.
///
/// As expressões regulares são compiladas na primeira chamada, portanto a primeira
/// execução pode ser mais lenta. Chamadas subsequentes reutilizam as regexes compiladas.
#[pyfunction]
pub fn padronizar_bairros(valor: &str) -> String {
    enderecobr_rs::padronizar_bairros(valor)
}

/// Padroniza uma string representando municípios brasileiros.
///
/// Parameters
/// ----------
/// valor : str
///     String contendo o nome ou código de um município brasileiro.
///     Pode ser nome (com variações de caixa, acentos, espaçamento),
///     código IBGE (7 ou 8 dígitos, com ou sem zeros à esquerda), ou string vazia.
///
/// Returns
/// -------
/// str
///     Nome canônico do município em caixa alta, sem acentos, com correções
///     ortográficas e atualizações conforme o IBGE 2022. **Valores que não
///     casem com nenhum município conhecido** (nem por grafia exata, nem por
///     aproximação fonética) **retornam string vazia** — trate `""` como
///     "município desconhecido".
///
/// Examples
/// --------
/// >>> import enderecobr
/// >>> enderecobr.padronizar_municipios("3304557")
/// 'RIO DE JANEIRO'
/// >>> enderecobr.padronizar_municipios("003304557")
/// 'RIO DE JANEIRO'
/// >>> enderecobr.padronizar_municipios("  3304557  ")
/// 'RIO DE JANEIRO'
/// >>> enderecobr.padronizar_municipios("RIO DE JANEIRO")
/// 'RIO DE JANEIRO'
/// >>> enderecobr.padronizar_municipios("rio de janeiro")
/// 'RIO DE JANEIRO'
/// >>> enderecobr.padronizar_municipios("SÃO PAULO")
/// 'SAO PAULO'
/// >>> enderecobr.padronizar_municipios("PARATI")
/// 'PARATY'
/// >>> enderecobr.padronizar_municipios("AUGUSTO SEVERO")
/// 'CAMPO GRANDE'
/// >>> enderecobr.padronizar_municipios("SAO VALERIO DA NATIVIDADE")
/// 'SAO VALERIO'
/// >>> enderecobr.padronizar_municipios("LAGOA DANTA")
/// "LAGOA D'ANTA"
/// >>> enderecobr.padronizar_municipios("")  # entrada vazia
/// ''
/// >>> enderecobr.padronizar_municipios("BANANA")  # irreconhecível
/// ''
/// >>> enderecobr.padronizar_municipios("!!!!")  # sem conteúdo útil
/// ''
/// >>> enderecobr.padronizar_municipios("PARATI!!!!")  # ruído descartado antes da busca
/// 'PARATY'
///
/// Notes
/// -----
/// As seguintes operações são realizadas:
///
/// - Remoção de espaços em branco no início/fim e excesso entre palavras.
/// - Conversão para caixa alta.
/// - Remoção de zeros à esquerda em códigos numéricos.
/// - Busca do nome completo do município a partir do código IBGE.
/// - Remoção de acentos e caracteres não ASCII.
/// - Correção de erros ortográficos comuns e nomes desatualizados,
///   com base na lista oficial de municípios do IBGE (2022).
///
/// As expressões regulares são compiladas na primeira chamada, portanto a primeira
/// execução pode ser mais lenta. Chamadas subsequentes reutilizam as regexes compiladas.
#[pyfunction]
pub fn padronizar_municipios(valor: &str) -> String {
    enderecobr_rs::padronizar_municipios(valor)
}

/// Padroniza uma string representando estados brasileiros para seu nome por extenso,
/// porém sem diacríticos.
///
/// Parameters
/// ----------
/// valor : str
///     String contendo o código numérico (ex: '21', '021'), sigla (ex: 'MA', 'ma') ou nome
///     de um estado brasileiro. Pode conter espaços extras ou formatação irregular.
///
/// Returns
/// -------
/// str
///     Nome por extenso do estado em caixa alta e sem diacríticos (ex: 'MARANHAO').
///     Retorna string vazia se o valor for inválido, vazio ou não corresponder a um estado.
///
/// Notes
/// -----
/// Operações realizadas durante a padronização:
///
/// - Remoção de espaços em branco no início e fim, e espaços extras internos;
/// - Conversão para caixa alta;
/// - Remoção de zeros à esquerda (em códigos numéricos);
/// - Mapeamento partir do código numérico ou da abreviação da UF, do nome completo de cada estado.
///
/// Examples
/// --------
/// >>> import enderecobr
/// >>> enderecobr.padronizar_estados_para_nome("21")
/// 'MARANHAO'
/// >>> enderecobr.padronizar_estados_para_nome("021")
/// 'MARANHAO'
/// >>> enderecobr.padronizar_estados_para_nome("MA")
/// 'MARANHAO'
/// >>> enderecobr.padronizar_estados_para_nome(" 21")
/// 'MARANHAO'
/// >>> enderecobr.padronizar_estados_para_nome(" MA ")
/// 'MARANHAO'
/// >>> enderecobr.padronizar_estados_para_nome("ma")
/// 'MARANHAO'
/// >>> enderecobr.padronizar_estados_para_nome("")
/// ''
/// >>> enderecobr.padronizar_estados_para_nome("me")
/// ''
/// >>> enderecobr.padronizar_estados_para_nome("maranhao")
/// 'MARANHAO'
#[pyfunction]
pub fn padronizar_estados_para_nome(valor: &str) -> &'static str {
    enderecobr_rs::padronizar_estados_para_nome(valor)
}

/// Padroniza uma string representando estados brasileiros para o código do IBGE.
///
/// Parameters
/// ----------
/// valor : str
///     Código numérico (ex: 21, 021), sigla (ex: MA, ma) ou nome de
///     um estado brasileiro.
///
/// Returns
/// -------
/// str
///     Código do IBGE do estado (ex: 21), em caixa alta. Retorna string vazia
///     se o valor for inválido, vazio ou não corresponder a um estado.
///
/// Examples
/// --------
/// >>> import enderecobr
/// >>> enderecobr.padronizar_estados_para_codigo('21')
/// '21'
/// >>> enderecobr.padronizar_estados_para_codigo('021')
/// '21'
/// >>> enderecobr.padronizar_estados_para_codigo('MA')
/// '21'
/// >>> enderecobr.padronizar_estados_para_codigo('')
/// ''
/// >>> enderecobr.padronizar_estados_para_codigo('me')
/// ''
/// >>> enderecobr.padronizar_estados_para_codigo('maranhao')
/// '21'
#[pyfunction]
pub fn padronizar_estados_para_codigo(valor: &str) -> &'static str {
    enderecobr_rs::padronizar_estados_para_codigo(valor)
}

/// Padroniza uma string representando estados brasileiros para sua sigla de duas letras.
///
/// Parameters
/// ----------
/// valor : str
///     Código numérico (ex: 21, 021), sigla (ex: MA, ma) ou nome de
///     um estado brasileiro.
///
/// Returns
/// -------
/// str
///     Sigla da UF em caixa alta (ex: MA). Retorna string vazia se o valor for
///     inválido, vazio ou não corresponder a um estado.
///
/// Examples
/// --------
/// >>> import enderecobr
/// >>> enderecobr.padronizar_estados_para_sigla('21')
/// 'MA'
/// >>> enderecobr.padronizar_estados_para_sigla('021')
/// 'MA'
/// >>> enderecobr.padronizar_estados_para_sigla('MA')
/// 'MA'
/// >>> enderecobr.padronizar_estados_para_sigla('')
/// ''
/// >>> enderecobr.padronizar_estados_para_sigla('me')
/// ''
/// >>> enderecobr.padronizar_estados_para_sigla('maranhao')
/// 'MA'
#[pyfunction]
pub fn padronizar_estados_para_sigla(valor: &str) -> &'static str {
    enderecobr_rs::padronizar_estados_para_sigla(valor)
}

/// Padroniza uma string representando complementos de logradouros.
///
/// Examples
/// --------
/// >>> import enderecobr
/// >>> enderecobr.padronizar_tipo_logradouro("R")
/// 'RUA'
/// >>> enderecobr.padronizar_tipo_logradouro("AVE")
/// 'AVENIDA'
/// >>> enderecobr.padronizar_tipo_logradouro("QDRA")
/// 'QUADRA'
///
/// Notes
/// -----
/// Operações realizadas durante a padronização:
///
/// - Remoção de espaços em branco antes e depois das strings e remoção de espaços em excesso entre palavras.
/// - Conversão de caracteres para caixa alta.
/// - Remoção de acentos e caracteres não ASCII.
/// - Adição de espaços após abreviações sinalizadas por pontos.
/// - Expansão de abreviações frequentemente utilizadas através de expressões regulares.
/// - Correção de pequenos erros ortográficos.
///
/// A primeira chamada pode ser mais lenta devido à compilação inicial das expressões regulares.
#[pyfunction]
pub fn padronizar_tipo_logradouro(valor: &str) -> String {
    enderecobr_rs::padronizar_tipo_logradouro(valor)
}

/// Padroniza CEPs em formato textual para uma string formatada.
///
/// Completa com zeros à esquerda quando necessário e retorna erro se o valor
/// contiver caracteres inválidos ou exceder o tamanho permitido de CEP.
///
/// Parameters
/// ----------
/// valor : str
///     CEP em formato textual (ex: 12345-6, a123b45 6 sem os inválidos).
///
/// Returns
/// -------
/// str
///     CEP padronizado no formato XXXXX-XXX.
///
/// Raises
/// ------
/// ValueError
///     Se o CEP tiver caracteres inválidos ou muitos dígitos.
///
/// Examples
/// --------
/// >>> import enderecobr
/// >>> enderecobr.padronizar_cep('12345-6')
/// '00123-456'
#[pyfunction]
pub fn padronizar_cep(valor: &str) -> PyResult<String> {
    enderecobr_rs::cep::padronizar_cep(valor).map_err(PyValueError::new_err)
}

/// Padroniza um CEP numérico para uma string formatada.
///
/// Completa com zeros à esquerda quando necessário e retorna erro se o valor
/// exceder o tamanho permitido de CEP. O valor precisa ser inteiro e não
/// negativo.
///
/// Parameters
/// ----------
/// valor : int
///     CEP em formato numérico (ex: 123456).
///
/// Returns
/// -------
/// str
///     CEP padronizado no formato XXXXX-XXX.
///
/// Raises
/// ------
/// ValueError
///     Se o CEP tiver muitos dígitos ou se o valor for negativo.
///
/// Examples
/// --------
/// >>> import enderecobr
/// >>> enderecobr.padronizar_cep_numerico(123456)
/// '00123-456'
#[pyfunction]
pub fn padronizar_cep_numerico(valor: i32) -> PyResult<String> {
    enderecobr_rs::cep::padronizar_cep_numerico(valor).map_err(PyValueError::new_err)
}

/// Padroniza CEPs em formato textual para uma string formatada, tentando corrigir possíveis erros.
///
/// Esta função ignora quaisquer caracteres não numéricos, além de remover números
/// extras e completar com zeros à esquerda quando necessário.
///
/// Parameters
/// ----------
/// valor : str
///     CEP em formato textual, que pode conter caracteres não numéricos e formatação irregular.
///
/// Returns
/// -------
/// str
///     CEP padronizado no formato XXXXX-XXX (com 8 dígitos, separados por hífen, completado com zeros à esquerda se necessário).
///
/// Examples
/// --------
/// >>> import enderecobr
/// >>> enderecobr.padronizar_cep_leniente("a123b45  6")
/// '00123-456'
///
/// Notes
/// -----
/// - São extraídos apenas os dígitos numéricos da entrada.
/// - Se mais de 8 dígitos forem fornecidos, apenas os 8 primeiros são considerados.
/// - Se menos de 8 dígitos forem fornecidos, zeros são adicionados à esquerda.
#[pyfunction]
pub fn padronizar_cep_leniente(valor: &str) -> String {
    enderecobr_rs::padronizar_cep_leniente(valor)
}

/// Padroniza uma string representando números de logradouros para um inteiro.
///
/// Remove zeros à esquerda; variações de SN (S/N, S N etc.) resultam em None.
/// Apenas números simples (sem espaços) são convertidos.
///
/// Parameters
/// ----------
/// valor : str
///     Texto bruto representando o número de um logradouro.
///
/// Returns
/// -------
/// int or None
///     Número convertido, ou None caso a entrada seja inválida, vazia,
///     sem número ou contenha mais de um número.
///
/// Examples
/// --------
/// >>> import enderecobr
/// >>> enderecobr.padronizar_numeros_para_int('0210')
/// 210
/// >>> enderecobr.padronizar_numeros_para_int('001')
/// 1
/// >>> enderecobr.padronizar_numeros_para_int('1')
/// 1
/// >>> enderecobr.padronizar_numeros_para_int('0') is None
/// True
/// >>> enderecobr.padronizar_numeros_para_int('') is None
/// True
/// >>> enderecobr.padronizar_numeros_para_int('S/N') is None
/// True
/// >>> enderecobr.padronizar_numeros_para_int('0180 0181') is None
/// True
#[pyfunction]
pub fn padronizar_numeros_para_int(valor: &str) -> Option<u32> {
    enderecobr_rs::padronizar_numeros_para_int(valor)
}

/// Converte um valor numérico para a representação textual de número de logradouro.
///
/// Valores menores ou iguais a zero são convertidos para S/N; valores decimais
/// são truncados.
///
/// Parameters
/// ----------
/// valor : int or float
///     Número a ser convertido.
///
/// Returns
/// -------
/// str
///     Representação textual do número, ou S/N para valores não positivos.
///
/// Examples
/// --------
/// >>> import enderecobr
/// >>> enderecobr.padronizar_numeros_para_string(210)
/// '210'
/// >>> enderecobr.padronizar_numeros_para_string(1.1)
/// '1'
/// >>> enderecobr.padronizar_numeros_para_string(0)
/// 'S/N'
/// >>> enderecobr.padronizar_numeros_para_string(-11)
/// 'S/N'
#[pyfunction]
pub fn padronizar_numeros_para_string(valor: f64) -> String {
    enderecobr_rs::padronizar_numeros_para_string(valor)
}

/// Normaliza uma string para processamento posterior, removendo diacríticos e
/// caracteres especiais, convertendo para maiúsculas e reduzindo espaços.
///
/// Parameters
/// ----------
/// valor : str
///     Texto bruto a ser normalizado.
///
/// Returns
/// -------
/// str
///     Texto normalizado: maiúsculas, sem acentos, com espaços das pontas
///     removidos e espaços internos reduzidos a um único espaço.
///
/// Examples
/// --------
/// >>> import enderecobr
/// >>> enderecobr.normalizar('Olá, mundo')
/// 'OLA, MUNDO'
/// >>> enderecobr.normalizar('R. DO AÇAÍ 15º')
/// 'R. DO ACAI 15O'
#[pyfunction]
pub fn normalizar(valor: &str) -> String {
    enderecobr_rs::normalizar(valor).to_string()
}

/// Identifica se uma string representa um dado faltante.
///
/// Parameters
/// ----------
/// valor : str
///     Texto a ser verificado.
///
/// Returns
/// -------
/// bool
///     True se o texto corresponder a um padrão de dado faltante
///     (ex: SI, NS, NI, NA), False caso contrário.
///
/// Examples
/// --------
/// >>> import enderecobr
/// >>> enderecobr.is_dado_faltante('SI')
/// True
/// >>> enderecobr.is_dado_faltante('SEM INFORMAÇÃO')
/// True
/// >>> enderecobr.is_dado_faltante('NA')
/// True
/// >>> enderecobr.is_dado_faltante('N CONSTA')
/// True
/// >>> enderecobr.is_dado_faltante('RUA B')
/// False
#[pyfunction]
pub fn is_dado_faltante(valor: &str) -> bool {
    enderecobr_rs::is_dado_faltante(valor)
}

/// Gera um código fonético (Metaphone-BR adaptado) para nomes em português.
///
/// Aplica transformações fonéticas a um nome visando representar sua pronúncia
/// aproximada em português brasileiro. Útil para agrupar nomes com sonoridade
/// similar, mesmo com grafias diferentes.
///
/// Parameters
/// ----------
/// valor : str
///     Nome ou texto a ser convertido em código fonético. Pode conter acentos,
///     caracteres especiais, espaços e letras minúsculas.
///
/// Returns
/// -------
/// str
///     Código fonético em maiúsculas, com transformações aplicadas segundo regras
///     adaptadas do Metaphone para o português brasileiro.
///
/// Notes
/// -----
/// O processo inclui:
///
///     - Remoção de acentos, números e conversão para maiúsculas;
///     - Eliminação de letras silenciosas (ex: 'H' inicial);
///     - Simplificação de dígrafos (ex: 'LH' → 'L', 'CH' → 'X');
///     - Agrupamento de consoantes com sonoridade similar (ex: C/K/S, G/J);
///     - Tratamento de sons nasais e vogais duplicadas;
///     - Compactação de espaços e letras repetidas.
///
/// Esta é uma adaptação que não segue rigorosamente nenhum algoritmo Metaphone
/// publicado, mas foi inspirada neles, considerando o contexto do português brasileiro.
///
/// Examples
/// --------
/// >>> enderecobr.metaphone("João Silva")
/// 'JOAO SILVA'
/// >>> enderecobr.metaphone("Marya")
/// 'MARIA'
/// >>> enderecobr.metaphone("Helena")
/// 'ELENA'
/// >>> enderecobr.metaphone("Philippe")
/// 'FILIPE'
/// >>> enderecobr.metaphone("Chavier")
/// 'XAVIER'
/// >>> enderecobr.metaphone("Maçã")
/// 'MASA'
#[pyfunction]
pub fn metaphone(valor: &str) -> String {
    enderecobr_rs::metaphone::metaphone(valor)
}
