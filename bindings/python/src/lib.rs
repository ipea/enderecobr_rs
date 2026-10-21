use std::path::PathBuf;

use pyo3::exceptions::{PyRuntimeError, PyValueError};
use pyo3::prelude::*;

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

    /// Adiciona uma regra simples de substituição.
    ///
    /// Toda ocorrência de `regex` será substituída por `substituicao`. É necessário
    /// chamar [`preparar`][Self::preparar] após adicionar regras manualmente.
    fn adicionar(&mut self, regex: &str, substituicao: &str) {
        self.interno.adicionar(regex, substituicao);
    }

    /// Adiciona uma regra condicional de substituição (com regex de exclusão).
    ///
    /// `regex` é substituída por `substituicao` somente se `regex_ignorar` **não**
    /// corresponder ao texto. É necessário chamar
    /// [`preparar`][Self::preparar] após adicionar regras manualmente.
    fn adicionar_com_ignorar(&mut self, regex: &str, substituicao: &str, regex_ignorar: &str) {
        self.interno
            .adicionar_com_ignorar(regex, substituicao, regex_ignorar);
    }

    /// Adiciona regras a partir de três vetores paralelos.
    ///
    /// Os vetores devem ter o mesmo comprimento. O terceiro vetor pode conter `None`
    /// para indicar ausência de condição de exclusão. As regras são preparadas
    /// automaticamente ao término da execução.
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

    /// Recompila o conjunto de expressões regulares após adicionar regras manualmente.
    ///
    /// Deve ser chamado após [`adicionar`][Self::adicionar] ou
    /// [`adicionar_com_ignorar`][Self::adicionar_com_ignorar] para que as novas
    /// regras passem a ser aplicadas.
    fn preparar(&mut self) {
        self.interno.preparar();
    }

    fn padronizar(&self, valor: &str) -> String {
        self.interno.padronizar(valor)
    }

    fn obter_substituicoes(&self) -> Vec<(&str, &str, Option<&str>)> {
        self.interno.obter_pares()
    }

    /// Retorna as regras como três vetores paralelos: regexes, substituições e
    /// regexes de exclusão.
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

    /// Adiciona novas expressões regulares ao identificador.
    fn adicionar(&mut self, regexs: Vec<String>) {
        self.interno.adicionar(&regexs);
    }

    /// Verifica se alguma das regexes cadastradas corresponde ao valor.
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

    /// Cria um separador já carregado a partir de um arquivo de modelo.
    #[staticmethod]
    fn carregar(caminho: PathBuf) -> PyResult<SeparadorEndereco> {
        Ok(SeparadorEndereco {
            interno: Some(abrir_modelo(caminho)?),
        })
    }

    /// Carrega (ou substitui) o modelo desta instância, sem criar um objeto novo.
    fn carregar_modelo(&mut self, caminho: PathBuf) -> PyResult<()> {
        self.interno = Some(abrir_modelo(caminho)?);
        Ok(())
    }

    /// Segmenta o endereço nas suas partes constituintes.
    fn segmentar(&self, py: Python<'_>, texto: &str) -> PyResult<EnderecoSegmentado> {
        let separador = self.interno.as_ref().ok_or_else(|| {
            PyRuntimeError::new_err(
                "Nenhum modelo carregado. Use SeparadorEndereco.carregar(caminho) \
                 ou carregar_modelo(caminho) antes de segmentar.",
            )
        })?;

        // A inferência do modelo é a parte cara: rodar sem o GIL libera as outras
        // threads do Python (a tagger é criada a cada chamada).
        let (segmentado, _, _) = py.detach(|| separador.segmentar_endereco_com_timing(texto));
        Ok(segmentado.into())
    }
}

/// Converte o `Result<_, String>` do núcleo no erro Python correspondente.
fn abrir_modelo(
    caminho: PathBuf,
) -> PyResult<enderecobr_rs::separador_endereco::SeparadorEndereco> {
    enderecobr_rs::separador_endereco::SeparadorEndereco::carregar(caminho).map_err(|erro| {
        PyRuntimeError::new_err(format!("Não foi possível carregar o modelo: {erro}"))
    })
}

/// Converte as falhas de resolução/download do modelo em erro Python.
fn erro_de_modelo(erro: String) -> PyErr {
    PyRuntimeError::new_err(format!("Não foi possível obter o modelo: {erro}"))
}

#[pyclass(get_all, frozen, eq, skip_from_py_object)]
#[derive(Clone, Debug, PartialEq)]
pub struct SegmentoEndereco {
    pub tipo: String,
    pub valor: String,
}

#[pyclass(get_all, frozen, eq, skip_from_py_object)]
#[derive(Clone, Debug, PartialEq)]
pub struct EnderecoSegmentado {
    pub segmentos: Vec<SegmentoEndereco>,
}

impl From<enderecobr_rs::separador_endereco::SegmentoEndereco> for SegmentoEndereco {
    fn from(s: enderecobr_rs::separador_endereco::SegmentoEndereco) -> Self {
        SegmentoEndereco {
            tipo: s.tipo,
            valor: s.valor,
        }
    }
}
impl From<enderecobr_rs::separador_endereco::EnderecoSegmentado> for EnderecoSegmentado {
    fn from(s: enderecobr_rs::separador_endereco::EnderecoSegmentado) -> Self {
        EnderecoSegmentado {
            segmentos: s
                .segmentos
                .into_iter()
                .map(SegmentoEndereco::from)
                .collect(),
        }
    }
}

#[pymodule]
pub mod enderecobr {

    use std::path::PathBuf;

    use pyo3::prelude::*;

    #[pymodule_export]
    use super::EnderecoSegmentado;

    #[pymodule_export]
    use super::SegmentoEndereco;

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
    fn obter_modelo(py: Python<'_>, path_modelo: Option<String>) -> PyResult<PathBuf> {
        // O download é bloqueante (até 60 s): não segurar o GIL enquanto isso.
        py.detach(|| enderecobr_rs::separador_endereco::obter_modelo(path_modelo))
            .map_err(super::erro_de_modelo)
    }

    #[pyfunction]
    #[pyo3(signature = (path_modelo = None))]
    fn obter_caminho_modelo(path_modelo: Option<String>) -> PyResult<PathBuf> {
        enderecobr_rs::separador_endereco::obter_caminho_modelo(path_modelo)
            .map_err(super::erro_de_modelo)
    }

    // ========= Separador de endereço ==========

    #[pyfunction]
    fn segmentar_endereco(endereco: &str) -> EnderecoSegmentado {
        enderecobr_rs::segmentar_endereco(endereco).into()
    }
}
