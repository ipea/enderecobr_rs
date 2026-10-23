use std::path::PathBuf;

use pyo3::exceptions::{PyRuntimeError, PyValueError};
use pyo3::prelude::*;

// As docstrings públicas ficam em `enderecobr.pyi`; aqui só ficam os
// comentários necessários para entender o código.

#[pyclass]
struct Padronizador {
    interno: enderecobr_rs::Padronizador,
}

#[pymethods]
impl Padronizador {
    #[new]
    fn novo() -> Padronizador {
        Padronizador {
            interno: enderecobr_rs::Padronizador::default(),
        }
    }

    fn adicionar_substituicoes(&mut self, pares: Vec<Vec<Option<String>>>) {
        // PS: Aparentemente preciso que seja um Vec de Vec quando não uso
        // os struct específicos do PyO3.

        // Converte Option<String> em Option<&str>
        let pares_str: Vec<Vec<Option<&str>>> = pares
            .iter()
            .map(|inner| inner.iter().map(|opt| opt.as_deref()).collect())
            .collect();

        // Converte para um vetor de slices
        let slices: Vec<&[Option<&str>]> = pares_str.iter().map(Vec::as_slice).collect();

        self.interno.adicionar_pares(&slices);
    }

    fn adicionar(&mut self, regex: &str, substituicao: &str) {
        self.interno.adicionar(regex, substituicao);
    }

    fn adicionar_com_ignorar(&mut self, regex: &str, substituicao: &str, regex_ignorar: &str) {
        self.interno
            .adicionar_com_ignorar(regex, substituicao, regex_ignorar);
    }

    fn adicionar_vetores(
        &mut self,
        regexes: Vec<String>,
        substituicoes: Vec<String>,
        regex_ignorar: Vec<Option<String>>,
    ) -> PyResult<()> {
        if regexes.len() != substituicoes.len() || regexes.len() != regex_ignorar.len() {
            return Err(PyValueError::new_err(
                "Os três vetores devem ter o mesmo comprimento.",
            ));
        }

        let regexes_ref: Vec<&str> = regexes.iter().map(|s| s.as_str()).collect();
        let substituicoes_ref: Vec<&str> = substituicoes.iter().map(|s| s.as_str()).collect();
        let ignorar_ref: Vec<Option<&str>> = regex_ignorar.iter().map(|o| o.as_deref()).collect();

        self.interno
            .adicionar_vetores(&regexes_ref, &substituicoes_ref, &ignorar_ref);
        Ok(())
    }

    fn preparar(&mut self) {
        self.interno.preparar();
    }

    fn padronizar(&self, valor: &str) -> String {
        self.interno.padronizar(valor)
    }

    fn obter_substituicoes(&self) -> Vec<(&str, &str, Option<&str>)> {
        self.interno.obter_pares()
    }

    fn obter_vetores(&self) -> (Vec<&str>, Vec<&str>, Vec<Option<&str>>) {
        self.interno.obter_vetores()
    }
}

#[pyclass]
struct IdentificadorPadroes {
    interno: enderecobr_rs::IdentificadorPadroes,
}

#[pymethods]
impl IdentificadorPadroes {
    #[new]
    fn novo() -> IdentificadorPadroes {
        IdentificadorPadroes {
            interno: enderecobr_rs::IdentificadorPadroes::default(),
        }
    }

    fn adicionar(&mut self, regexs: Vec<String>) {
        self.interno.adicionar(&regexs);
    }

    fn identificar(&self, valor: &str) -> bool {
        self.interno.identificar(valor)
    }
}

/// Segmentador probabilístico de endereços.
///
/// A instância nasce **sem modelo**: o construtor não lê nem baixa nada.
#[pyclass]
struct SeparadorEndereco {
    interno: Option<enderecobr_rs::separador_endereco::SeparadorEndereco>,
}

#[pymethods]
impl SeparadorEndereco {
    #[new]
    fn novo() -> SeparadorEndereco {
        SeparadorEndereco { interno: None }
    }

    #[staticmethod]
    fn carregar(caminho: PathBuf) -> PyResult<SeparadorEndereco> {
        Ok(SeparadorEndereco {
            interno: Some(abrir_modelo(caminho)?),
        })
    }

    fn carregar_modelo(&mut self, caminho: PathBuf) -> PyResult<()> {
        self.interno = Some(abrir_modelo(caminho)?);
        Ok(())
    }

    fn segmentar(&self, py: Python<'_>, texto: &str) -> PyResult<EnderecoSegmentado> {
        let separador = self.modelo()?;

        // A inferência é a parte cara: rodar sem o GIL libera as outras threads.
        Ok(py.detach(|| separador.segmentar(texto)).into())
    }

    fn segmentar_enderecos(
        &self,
        py: Python<'_>,
        textos: Vec<String>,
    ) -> PyResult<Vec<EnderecoSegmentado>> {
        let separador = self.modelo()?;

        let segmentados = py.detach(|| {
            let textos: Vec<&str> = textos.iter().map(String::as_str).collect();
            separador.segmentar_enderecos(&textos)
        });
        Ok(segmentados
            .into_iter()
            .map(EnderecoSegmentado::from)
            .collect())
    }
}

impl SeparadorEndereco {
    fn modelo(&self) -> PyResult<&enderecobr_rs::separador_endereco::SeparadorEndereco> {
        self.interno.as_ref().ok_or_else(|| {
            PyRuntimeError::new_err(
                "Nenhum modelo carregado. Use SeparadorEndereco.carregar(caminho) \
                 ou carregar_modelo(caminho) antes de segmentar.",
            )
        })
    }
}

/// Converte o `Result<_, String>` da lib Rust no erro Python correspondente.
fn abrir_modelo(
    caminho: PathBuf,
) -> PyResult<enderecobr_rs::separador_endereco::SeparadorEndereco> {
    // A mensagem da lib Rust já diz qual arquivo falhou e por quê.
    enderecobr_rs::separador_endereco::SeparadorEndereco::carregar(caminho)
        .map_err(PyRuntimeError::new_err)
}

/// Converte as falhas de resolução/download do modelo em erro Python.
fn erro_de_modelo(erro: String) -> PyErr {
    PyRuntimeError::new_err(format!("Não foi possível obter o modelo: {erro}"))
}

/// Converte a falha de carga do modelo padrão em erro Python.
fn erro_de_modelo_padrao(erro: String) -> PyErr {
    PyRuntimeError::new_err(format!("Não foi possível carregar o modelo padrão: {erro}"))
}

// ====== Endereço ======
#[pyclass(eq, skip_from_py_object)]
#[derive(Clone, Debug, PartialEq)]
pub struct Endereco {
    interno: enderecobr_rs::endereco::Endereco,
}

#[pymethods]
impl Endereco {
    #[new]
    #[pyo3(signature = (logradouro = None, numero = None, complemento = None, localidade = None, cep = None))]
    fn novo(
        logradouro: Option<String>,
        numero: Option<String>,
        complemento: Option<String>,
        localidade: Option<String>,
        cep: Option<String>,
    ) -> Endereco {
        Endereco {
            interno: enderecobr_rs::Endereco::novo(
                logradouro,
                numero,
                complemento,
                localidade,
                cep,
            ),
        }
    }

    #[getter]
    fn logradouro(&self) -> Option<String> {
        self.interno.logradouro.clone()
    }

    #[setter]
    fn set_logradouro(&mut self, valor: Option<String>) {
        self.interno.logradouro = valor;
    }

    #[getter]
    fn numero(&self) -> Option<String> {
        self.interno.numero.clone()
    }

    #[setter]
    fn set_numero(&mut self, valor: Option<String>) {
        self.interno.numero = valor;
    }

    #[getter]
    fn complemento(&self) -> Option<String> {
        self.interno.complemento.clone()
    }

    #[setter]
    fn set_complemento(&mut self, valor: Option<String>) {
        self.interno.complemento = valor;
    }

    #[getter]
    fn localidade(&self) -> Option<String> {
        self.interno.localidade.clone()
    }

    #[setter]
    fn set_localidade(&mut self, valor: Option<String>) {
        self.interno.localidade = valor;
    }

    #[getter]
    fn cep(&self) -> Option<String> {
        self.interno.cep.clone()
    }

    #[setter]
    fn set_cep(&mut self, valor: Option<String>) {
        self.interno.cep = valor;
    }

    fn formatar(&self) -> String {
        self.interno.formatar()
    }

    fn padronizar(&mut self) {
        self.interno.padronizar();
    }

    fn endereco_padronizado(&self) -> Endereco {
        self.interno.endereco_padronizado().into()
    }

    fn __str__(&self) -> String {
        self.interno.formatar()
    }

    fn __repr__(&self) -> String {
        format!(
            "Endereco(logradouro={}, numero={}, complemento={}, localidade={}, cep={})",
            formatar_campo(&self.interno.logradouro),
            formatar_campo(&self.interno.numero),
            formatar_campo(&self.interno.complemento),
            formatar_campo(&self.interno.localidade),
            formatar_campo(&self.interno.cep),
        )
    }
}

/// Mostra um campo opcional como `None` ou como texto entre aspas.
fn formatar_campo(campo: &Option<String>) -> String {
    campo
        .as_ref()
        .map_or_else(|| "None".to_string(), |valor| format!("{valor:?}"))
}

impl From<enderecobr_rs::Endereco> for Endereco {
    fn from(interno: enderecobr_rs::Endereco) -> Self {
        Self { interno }
    }
}

// ====== Classes do Segmentador ======

#[pyclass(eq, skip_from_py_object)]
#[derive(Clone, Debug, PartialEq)]
pub struct SegmentoEndereco {
    interno: enderecobr_rs::separador_endereco::SegmentoEndereco,
}

/// Espelha `enderecobr_rs::separador_endereco::TipoSegmento`: mesmas variantes, na
/// mesma ordem (a ordem define o valor inteiro usado por `eq_int`). Ao mexer em um
/// dos dois lados, mexa no outro.
#[pyclass(eq, eq_int, from_py_object)]
#[derive(Clone, Copy, Debug, PartialEq)]
pub enum TipoSegmento {
    Logradouro,
    LogradouroInterno,
    Numero,
    ModificadorNumero,
    Complemento,
    Cep,
    Localidade,
    Municipio,
    Uf,
    Parcela,
    QuilometragemVia,
    Denominacao,
    DescricaoArea,
    Empreendimento,
    Referencia,
    Outro,
}

#[pymethods]
impl SegmentoEndereco {
    #[new]
    #[pyo3(signature = (valor, tipo))]
    fn novo(valor: String, tipo: TipoSegmento) -> SegmentoEndereco {
        SegmentoEndereco {
            interno: enderecobr_rs::separador_endereco::SegmentoEndereco {
                valor,
                tipo: tipo.into(),
            },
        }
    }

    #[getter]
    fn tipo(&self) -> TipoSegmento {
        TipoSegmento::from(self.interno.tipo)
    }

    #[setter]
    fn set_tipo(&mut self, tipo: TipoSegmento) {
        self.interno.tipo = tipo.into();
    }

    #[getter]
    fn valor(&self) -> String {
        self.interno.valor.clone()
    }

    #[setter]
    fn set_valor(&mut self, valor: String) {
        self.interno.valor = valor;
    }

    fn __repr__(&self) -> String {
        format!(
            "SegmentoEndereco(valor={:?}, tipo={:?})",
            self.interno.valor, self.interno.tipo
        )
    }
}

#[pyclass(frozen, eq, skip_from_py_object)]
#[derive(Clone, Debug, PartialEq)]
pub struct EnderecoSegmentado {
    interno: enderecobr_rs::separador_endereco::EnderecoSegmentado,
}

#[pymethods]
impl EnderecoSegmentado {
    #[getter]
    fn segmentos(&self) -> Vec<SegmentoEndereco> {
        self.interno
            .segmentos
            .iter()
            .cloned()
            .map(SegmentoEndereco::from)
            .collect()
    }

    fn __repr__(&self) -> String {
        let segmentos: Vec<String> = self
            .interno
            .segmentos
            .iter()
            .map(|segmento| format!("({:?}, {:?})", segmento.valor, segmento.tipo))
            .collect();
        format!("EnderecoSegmentado([{}])", segmentos.join(", "))
    }
}

impl From<enderecobr_rs::separador_endereco::TipoSegmento> for TipoSegmento {
    fn from(interno: enderecobr_rs::separador_endereco::TipoSegmento) -> Self {
        use enderecobr_rs::separador_endereco::TipoSegmento as Rs;
        match interno {
            Rs::Logradouro => TipoSegmento::Logradouro,
            Rs::LogradouroInterno => TipoSegmento::LogradouroInterno,
            Rs::Numero => TipoSegmento::Numero,
            Rs::ModificadorNumero => TipoSegmento::ModificadorNumero,
            Rs::Complemento => TipoSegmento::Complemento,
            Rs::Cep => TipoSegmento::Cep,
            Rs::Localidade => TipoSegmento::Localidade,
            Rs::Municipio => TipoSegmento::Municipio,
            Rs::Uf => TipoSegmento::Uf,
            Rs::Parcela => TipoSegmento::Parcela,
            Rs::QuilometragemVia => TipoSegmento::QuilometragemVia,
            Rs::Denominacao => TipoSegmento::Denominacao,
            Rs::DescricaoArea => TipoSegmento::DescricaoArea,
            Rs::Empreendimento => TipoSegmento::Empreendimento,
            Rs::Referencia => TipoSegmento::Referencia,
            Rs::Outro => TipoSegmento::Outro,
        }
    }
}

impl From<TipoSegmento> for enderecobr_rs::separador_endereco::TipoSegmento {
    fn from(espelho: TipoSegmento) -> Self {
        use enderecobr_rs::separador_endereco::TipoSegmento as Rs;
        match espelho {
            TipoSegmento::Logradouro => Rs::Logradouro,
            TipoSegmento::LogradouroInterno => Rs::LogradouroInterno,
            TipoSegmento::Numero => Rs::Numero,
            TipoSegmento::ModificadorNumero => Rs::ModificadorNumero,
            TipoSegmento::Complemento => Rs::Complemento,
            TipoSegmento::Cep => Rs::Cep,
            TipoSegmento::Localidade => Rs::Localidade,
            TipoSegmento::Municipio => Rs::Municipio,
            TipoSegmento::Uf => Rs::Uf,
            TipoSegmento::Parcela => Rs::Parcela,
            TipoSegmento::QuilometragemVia => Rs::QuilometragemVia,
            TipoSegmento::Denominacao => Rs::Denominacao,
            TipoSegmento::DescricaoArea => Rs::DescricaoArea,
            TipoSegmento::Empreendimento => Rs::Empreendimento,
            TipoSegmento::Referencia => Rs::Referencia,
            TipoSegmento::Outro => Rs::Outro,
        }
    }
}

impl From<enderecobr_rs::separador_endereco::SegmentoEndereco> for SegmentoEndereco {
    fn from(interno: enderecobr_rs::separador_endereco::SegmentoEndereco) -> Self {
        Self { interno }
    }
}

impl From<enderecobr_rs::separador_endereco::EnderecoSegmentado> for EnderecoSegmentado {
    fn from(interno: enderecobr_rs::separador_endereco::EnderecoSegmentado) -> Self {
        Self { interno }
    }
}

#[pymodule]
pub mod enderecobr {

    use std::path::PathBuf;

    use pyo3::prelude::*;

    #[pymodule_export]
    use super::EnderecoSegmentado;

    #[pymodule_export]
    use super::Endereco;

    #[pymodule_export]
    use super::SegmentoEndereco;

    #[pymodule_export]
    use super::TipoSegmento;

    #[pymodule_export]
    use super::Padronizador;

    #[pymodule_export]
    use super::IdentificadorPadroes;

    #[pymodule_export]
    use super::SeparadorEndereco;

    #[pyfunction]
    fn padronizar_logradouros(valor: &str) -> String {
        enderecobr_rs::padronizar_logradouros(valor)
    }

    #[pyfunction]
    fn padronizar_numeros(valor: &str) -> String {
        enderecobr_rs::padronizar_numeros(valor)
    }

    #[pyfunction]
    fn padronizar_complementos(valor: &str) -> String {
        enderecobr_rs::padronizar_complementos(valor)
    }

    #[pyfunction]
    fn padronizar_bairros(valor: &str) -> String {
        enderecobr_rs::padronizar_bairros(valor)
    }

    #[pyfunction]
    fn padronizar_municipios(valor: &str) -> String {
        enderecobr_rs::padronizar_municipios(valor)
    }

    #[pyfunction]
    fn padronizar_estados_para_nome(valor: &str) -> &'static str {
        enderecobr_rs::padronizar_estados_para_nome(valor)
    }

    #[pyfunction]
    fn padronizar_estados_para_codigo(valor: &str) -> &'static str {
        enderecobr_rs::padronizar_estados_para_codigo(valor)
    }

    #[pyfunction]
    fn padronizar_estados_para_sigla(valor: &str) -> &'static str {
        enderecobr_rs::padronizar_estados_para_sigla(valor)
    }

    #[pyfunction]
    fn padronizar_tipo_logradouro(valor: &str) -> String {
        enderecobr_rs::padronizar_tipo_logradouro(valor)
    }

    #[pyfunction]
    fn padronizar_cep(valor: &str) -> PyResult<String> {
        enderecobr_rs::cep::padronizar_cep(valor).map_err(pyo3::exceptions::PyValueError::new_err)
    }

    #[pyfunction]
    fn padronizar_cep_numerico(valor: i32) -> PyResult<String> {
        enderecobr_rs::cep::padronizar_cep_numerico(valor)
            .map_err(pyo3::exceptions::PyValueError::new_err)
    }

    #[pyfunction]
    fn padronizar_cep_leniente(valor: &str) -> String {
        enderecobr_rs::padronizar_cep_leniente(valor)
    }

    #[pyfunction]
    fn padronizar_numeros_para_int(valor: &str) -> Option<u32> {
        enderecobr_rs::padronizar_numeros_para_int(valor)
    }

    #[pyfunction]
    fn padronizar_numeros_para_string(valor: f64) -> String {
        enderecobr_rs::padronizar_numeros_para_string(valor)
    }

    #[pyfunction]
    fn normalizar(valor: &str) -> String {
        enderecobr_rs::normalizar(valor).to_string()
    }

    #[pyfunction]
    fn is_dado_faltante(valor: &str) -> bool {
        enderecobr_rs::is_dado_faltante(valor)
    }

    #[pyfunction]
    fn metaphone(valor: &str) -> String {
        enderecobr_rs::metaphone::metaphone(valor)
    }

    #[pyfunction]
    fn padronizar_numeros_por_extenso(valor: &str) -> String {
        enderecobr_rs::numero_extenso::padronizar_numeros_por_extenso(valor).to_string()
    }

    #[pyfunction]
    fn padronizar_numero_romano_por_extenso(valor: &str) -> String {
        enderecobr_rs::numero_extenso::padronizar_numero_romano_por_extenso(valor).to_string()
    }

    #[pyfunction]
    fn numero_por_extenso(valor: i32) -> String {
        enderecobr_rs::numero_extenso::numero_por_extenso(valor).to_string()
    }

    #[pyfunction]
    fn romano_para_inteiro(valor: &str) -> i32 {
        enderecobr_rs::numero_extenso::romano_para_inteiro(valor)
    }

    // ========= Padronizadores pré prontos ==========

    #[pyfunction]
    fn obter_padronizador_logradouros() -> Padronizador {
        Padronizador {
            interno: enderecobr_rs::logradouro::criar_padronizador_logradouros(),
        }
    }

    #[pyfunction]
    fn obter_padronizador_numeros() -> Padronizador {
        Padronizador {
            interno: enderecobr_rs::numero::criar_padronizador_numeros(),
        }
    }

    #[pyfunction]
    fn obter_padronizador_bairros() -> Padronizador {
        Padronizador {
            interno: enderecobr_rs::bairro::criar_padronizador_bairros(),
        }
    }

    #[pyfunction]
    fn obter_padronizador_complementos() -> Padronizador {
        Padronizador {
            interno: enderecobr_rs::complemento::criar_padronizador_complemento(),
        }
    }

    #[pyfunction]
    fn obter_padronizador_tipos_logradouros() -> Padronizador {
        Padronizador {
            interno: enderecobr_rs::tipo_logradouro::criar_padronizador_tipo_logradouro(),
        }
    }

    // ========= Gestão do Modelo ==========

    #[pyfunction]
    #[pyo3(signature = (path_modelo = None))]
    fn obter_modelo(py: Python<'_>, path_modelo: Option<PathBuf>) -> PyResult<PathBuf> {
        // O download é bloqueante (até 60 s): não segurar o GIL enquanto isso.
        py.detach(|| enderecobr_rs::separador_endereco::obter_modelo(path_modelo.as_deref()))
            .map_err(super::erro_de_modelo)
    }

    #[pyfunction]
    #[pyo3(signature = (path_modelo = None))]
    fn obter_caminho_modelo(path_modelo: Option<PathBuf>) -> PyResult<PathBuf> {
        enderecobr_rs::separador_endereco::obter_caminho_modelo(path_modelo.as_deref())
            .map_err(super::erro_de_modelo)
    }

    // ========= Separador de endereço ==========

    #[pyfunction]
    fn segmentar_endereco(py: Python<'_>, endereco: &str) -> PyResult<EnderecoSegmentado> {
        let segmentado = py
            .detach(|| enderecobr_rs::tentar_segmentar_endereco(endereco))
            .map_err(super::erro_de_modelo_padrao)?;
        Ok(segmentado.into())
    }

    #[pyfunction]
    fn segmentar_enderecos(
        py: Python<'_>,
        enderecos: Vec<String>,
    ) -> PyResult<Vec<EnderecoSegmentado>> {
        let segmentados = py
            .detach(|| {
                let textos: Vec<&str> = enderecos.iter().map(String::as_str).collect();
                enderecobr_rs::tentar_segmentar_enderecos(&textos)
            })
            .map_err(super::erro_de_modelo_padrao)?;
        Ok(segmentados
            .into_iter()
            .map(EnderecoSegmentado::from)
            .collect())
    }

    #[pyfunction]
    #[pyo3(signature = (endereco, padronizar = true))]
    fn estruturar_endereco(py: Python<'_>, endereco: &str, padronizar: bool) -> PyResult<Endereco> {
        let estruturado = py
            .detach(|| enderecobr_rs::tentar_estruturar_endereco(endereco, padronizar))
            .map_err(super::erro_de_modelo_padrao)?;
        Ok(estruturado.into())
    }
}

#[cfg(test)]
mod testes {
    use super::TipoSegmento;
    use enderecobr_rs::separador_endereco::TipoSegmento as TipoSegmentoRs;

    #[test]
    fn tipo_segmento_espelha_o_rust() {
        // Mesma quantidade, mesma ordem (a ordem vira o valor inteiro no Python)
        // e sem duas variantes do Rust caindo na mesma variante do Python.
        for (indice, tipo) in TipoSegmentoRs::TODOS.into_iter().enumerate() {
            let espelho = TipoSegmento::from(tipo);
            assert_eq!(
                espelho as isize, indice as isize,
                "ordem divergente: {tipo}"
            );
            assert_eq!(TipoSegmentoRs::from(espelho), tipo, "ida e volta: {tipo}");
        }
    }
}
