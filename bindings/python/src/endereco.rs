//! `Endereco`: os campos de um endereço já separados.

use pyo3::prelude::*;

/// Endereço com os campos já separados.
///
/// Pode ser criado vazio (`Endereco()`), com os campos que você já tem, ou
/// obtido a partir de um texto com `estruturar_endereco`. Campos ausentes
/// ficam como `None`.
///
/// Cria um endereço informando apenas os campos que existem.
///
/// Parameters
/// ----------
/// logradouro : str or None, optional
///     Nome do logradouro.
/// numero : str or None, optional
///     Número do imóvel.
/// complemento : str or None, optional
///     Complemento do imóvel.
/// localidade : str or None, optional
///     Bairro ou localidade.
/// cep : str or None, optional
///     CEP, que pode vir em qualquer formato (a padronização é feita
///     depois, por `padronizar`).
///
/// Attributes
/// ----------
/// logradouro : str or None
///     Nome do logradouro (rua, avenida etc.).
/// numero : str or None
///     Número do imóvel; `S/N` quando não houver.
/// complemento : str or None
///     Complemento do imóvel (apartamento, bloco, loja etc.).
/// localidade : str or None
///     Bairro ou localidade.
/// cep : str or None
///     CEP no formato `XXXXX-XXX`.
///
/// Examples
/// --------
/// Montando um endereço a partir de campos soltos:
///
/// >>> from enderecobr import Endereco
/// >>> end = Endereco(logradouro='r. gen glicerio', numero='1')
/// >>> end.padronizar()
/// >>> end.logradouro
/// 'RUA GENERAL GLICERIO'
#[pyclass(eq, skip_from_py_object, module = "enderecobr.enderecobr")]
#[derive(Clone, Debug, PartialEq)]
pub struct Endereco {
    interno: enderecobr_rs::Endereco,
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

    /// Probabilidade de a segmentação que originou este endereço estar correta.
    ///
    /// Cai com o tamanho do endereço; para comparar endereços de tamanhos
    /// diferentes, use `confianca`. `None` quando a segmentação não pediu as
    /// probabilidades (`com_probabilidade=False`).
    #[getter]
    fn probabilidade(&self) -> Option<f64> {
        self.interno.probabilidade
    }

    /// Certeza média por trecho, entre 0 e 1.
    ///
    /// É a média geométrica das probabilidades de cada token, então não cai com
    /// o tamanho do endereço. `None` quando a segmentação não pediu as
    /// probabilidades.
    #[getter]
    fn confianca(&self) -> Option<f64> {
        self.interno.confianca
    }

    /// Junta os campos preenchidos em um único texto, separados por vírgula.
    ///
    /// Campos `None` ou vazios são omitidos. É o mesmo texto devolvido por
    /// `str(endereco)`.
    ///
    /// Returns
    /// -------
    /// str
    ///     Texto com os campos preenchidos, na ordem logradouro, número,
    ///     complemento, localidade e CEP.
    ///
    /// Examples
    /// --------
    /// >>> end = Endereco(logradouro='r. gen glicerio', numero='1')
    /// >>> end.formatar()
    /// 'r. gen glicerio, 1'
    fn formatar(&self) -> String {
        self.interno.formatar()
    }

    /// Padroniza os campos deste endereço no próprio objeto.
    ///
    /// Cada campo passa pela função adequada (logradouro, número,
    /// complemento, bairro e CEP). Campos vazios continuam vazios.
    ///
    /// Examples
    /// --------
    /// >>> end = Endereco(logradouro='r. gen glicerio', numero='1')
    /// >>> end.padronizar()
    /// >>> end.logradouro
    /// 'RUA GENERAL GLICERIO'
    fn padronizar(&mut self) {
        self.interno.padronizar();
    }

    /// Devolve uma cópia padronizada, sem alterar o original.
    ///
    /// Returns
    /// -------
    /// Endereco
    ///     Novo endereço com os campos padronizados.
    ///
    /// Examples
    /// --------
    /// >>> end = Endereco(logradouro='r. gen glicerio', numero='1')
    /// >>> end.endereco_padronizado().logradouro
    /// 'RUA GENERAL GLICERIO'
    /// >>> end.logradouro
    /// 'r. gen glicerio'
    fn endereco_padronizado(&self) -> Endereco {
        self.interno.endereco_padronizado().into()
    }

    /// Serializa o endereço em JSON.
    ///
    /// As chaves seguem a ordem dos campos e os campos ausentes saem como
    /// `null` — o mesmo formato usado nos dumps de endereços estruturados.
    ///
    /// Returns
    /// -------
    /// str
    ///     JSON com as chaves `logradouro`, `numero`, `complemento`,
    ///     `localidade` e `cep`.
    ///
    /// Examples
    /// --------
    /// >>> end = Endereco(logradouro='r. gen glicerio', numero='1')
    /// >>> end.como_json()
    /// '{"logradouro":"r. gen glicerio","numero":"1","complemento":null,"localidade":null,"cep":null}'
    fn como_json(&self) -> String {
        self.interno.como_json()
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
