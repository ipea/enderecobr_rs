//! `Padronizador`, `IdentificadorPadroes` e os padronizadores prontos.

use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;

/// Estrutura para padronização condicional de textos de endereços usando expressões regulares.
///
/// Permite definir regras de substituição com condições de exclusão (``regex_ignorar``).
/// Usa um conjunto de regex compilado para acelerar a detecção de padrões.
///
/// Use `$1`, `$2`... para referenciar um grupo de captura na string de substituição.
///
/// Por usar o motor de expressões regulares do Rust, esta classe **NÃO** aceita o uso de:
///
/// - look-arounds -> ex: `^RUA(?!\\.)` (começa com "RUA", mas não deve ter um ponto após);
/// - backreferences -> ex: `(\\w+) \\1` (duas palavras iguais repetidas após um espaço);
///
///
/// Examples
/// --------
/// >>> from enderecobr import Padronizador
/// >>> pad = Padronizador()
/// >>> pad.adicionar_substituicoes([
/// ...     ["AV ", "AVENIDA "],
/// ...     ["^R ", "RUA ", "R APT"],
/// ... ])
/// >>> pad.padronizar("AV AZUL")
/// 'AVENIDA AZUL'
/// >>> pad.padronizar("R APT AMARELA")
/// 'R APT AMARELA'
#[pyclass(module = "enderecobr.enderecobr")]
pub struct Padronizador {
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

    /// Adiciona múltiplas regras de substituição a partir de uma lista de listas.
    ///
    /// Cada sublista representa uma regra no formato:
    /// [regex, substituição, regex_ignorar] (valores None são ignorados).
    ///
    /// Regras:
    ///
    /// - 1 item: equivalente a [regex, '']
    /// - 2 itens: equivalente a [regex, substituição]
    /// - 3 ou mais itens: equivalente a [regex, substituição, regex_ignorar]
    ///
    /// Parameters
    /// ----------
    /// pares : list of list of (str or None)
    ///     Lista de regras de substituição. Cada regra é uma lista com até três elementos.
    ///
    /// Examples
    /// --------
    /// >>> pad = Padronizador()
    /// >>> pad.adicionar_substituicoes([
    /// ...     ["R ", "RUA ", "APT R "],
    /// ...     ["AV ", "AVENIDA ", None],
    /// ...     ["NO ", "Nº"]
    /// ... ])
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
    /// Toda ocorrência de ``regex`` será substituída por ``substituicao``.
    /// É necessário chamar ``Padronizador.preparar`` após adicionar regras
    /// manualmente para que passem a valer.
    ///
    /// Parameters
    /// ----------
    /// regex : str
    ///     Expressão regular a ser substituída.
    /// substituicao : str
    ///     Texto de substituição (use ``$1``, ``$2``... para grupos capturados).
    ///
    /// Examples
    /// --------
    /// >>> pad = Padronizador()
    /// >>> pad.adicionar(r'R\.', 'RUA')
    /// >>> pad.preparar()
    /// >>> pad.padronizar('R. AZUL')
    /// 'RUA AZUL'
    fn adicionar(&mut self, regex: &str, substituicao: &str) {
        self.interno.adicionar(regex, substituicao);
    }

    /// Adiciona uma regra condicional de substituição (com regex de exclusão).
    ///
    /// ``regex`` é substituída por ``substituicao`` somente se ``regex_ignorar``
    /// não corresponder ao texto. É necessário chamar ``Padronizador.preparar``
    /// após adicionar regras manualmente.
    ///
    /// Parameters
    /// ----------
    /// regex : str
    ///     Expressão regular a ser substituída.
    /// substituicao : str
    ///     Texto de substituição.
    /// regex_ignorar : str
    ///     Expressão regular de exclusão.
    ///
    /// Examples
    /// --------
    /// >>> pad = Padronizador()
    /// >>> pad.adicionar_com_ignorar(r'^R ', 'RUA ', r'R APT')
    /// >>> pad.preparar()
    /// >>> pad.padronizar('R AMARELA')
    /// 'RUA AMARELA'
    /// >>> pad.padronizar('R APT AMARELA')
    /// 'R APT AMARELA'
    fn adicionar_com_ignorar(&mut self, regex: &str, substituicao: &str, regex_ignorar: &str) {
        self.interno
            .adicionar_com_ignorar(regex, substituicao, regex_ignorar);
    }

    /// Adiciona regras a partir de três vetores paralelos.
    ///
    /// Os vetores devem ter o mesmo comprimento. O terceiro vetor pode conter
    /// None para indicar ausência de condição de exclusão. As regras são
    /// preparadas automaticamente ao término da execução.
    ///
    /// Parameters
    /// ----------
    /// regexes : iterable of str
    ///     Expressões regulares a serem substituídas.
    /// substituicoes : iterable of str
    ///     Textos de substituição correspondentes.
    /// regex_ignorar : iterable of (str or None)
    ///     Expressões de exclusão correspondentes (ou None).
    ///
    /// Examples
    /// --------
    /// >>> pad = Padronizador()
    /// >>> pad.adicionar_vetores(['R ', 'AV '], ['RUA ', 'AVENIDA '], [None, None])
    /// >>> pad.padronizar('R AZUL')
    /// 'RUA AZUL'
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
    /// Deve ser chamado após ``Padronizador.adicionar`` ou
    /// ``Padronizador.adicionar_com_ignorar`` para que as novas regras
    /// passem a ser aplicadas.
    ///
    /// Examples
    /// --------
    /// >>> pad = Padronizador()
    /// >>> pad.adicionar(r'R\.', 'RUA')
    /// >>> pad.preparar()
    fn preparar(&mut self) {
        self.interno.preparar();
    }

    /// Aplica todas as regras de substituição ao texto, com normalização prévia.
    ///
    /// O texto é convertido para maiúsculas, acentos são removidos, e espaços
    /// extras são reduzidos. As regras são aplicadas em ordem, com condição de
    /// exclusão verificada antes de cada substituição.
    ///
    /// Parameters
    /// ----------
    /// valor : str
    ///     Texto de entrada a ser padronizado.
    ///
    /// Returns
    /// -------
    /// str
    ///     Texto padronizado.
    ///
    /// Examples
    /// --------
    /// >>> pad = Padronizador()
    /// >>> pad.adicionar_substituicoes([[r"\bR\b", "RUA"]])
    /// >>> pad.padronizar("  r amarela ")
    /// 'RUA AMARELA'
    fn padronizar(&self, valor: &str) -> String {
        self.interno.padronizar(valor)
    }

    /// Retorna as regras de substituição atuais.
    ///
    /// Returns
    /// -------
    /// list of tuple of (str, str, str or None)
    ///     Lista de triplas: (regex, substituição, regex_ignorar).
    ///
    /// Examples
    /// --------
    /// >>> pad = Padronizador()
    /// >>> pad.adicionar_substituicoes([["R ", "RUA "]])
    /// >>> pad.obter_substituicoes()
    /// [('R ', 'RUA ', None)]
    fn obter_substituicoes(&self) -> Vec<(&str, &str, Option<&str>)> {
        self.interno.obter_pares()
    }

    /// Retorna as regras como três vetores paralelos.
    ///
    /// Returns
    /// -------
    /// tuple of (list of str, list of str, list of (str or None))
    ///     Vetores ``(regex, substituicao, ignorar)``.
    ///
    /// Examples
    /// --------
    /// >>> pad = Padronizador()
    /// >>> pad.adicionar_substituicoes([['R ', 'RUA ']])
    /// >>> pad.obter_vetores()
    /// (['R '], ['RUA '], [None])
    fn obter_vetores(&self) -> (Vec<&str>, Vec<&str>, Vec<Option<&str>>) {
        self.interno.obter_vetores()
    }
}

/// Wrapper fino sobre um conjunto de expressões regulares compiladas para
/// identificar rapidamente padrões em textos.
///
/// Examples
/// --------
/// >>> from enderecobr import IdentificadorPadroes
/// >>> idp = IdentificadorPadroes()
/// >>> idp.adicionar(['RUA', 'AVENIDA'])
/// >>> idp.identificar('RUA AZUL')
/// True
/// >>> idp.identificar('TRAVESSA')
/// False
#[pyclass(module = "enderecobr.enderecobr")]
pub struct IdentificadorPadroes {
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
    ///
    /// Parameters
    /// ----------
    /// regexs : iterable of str
    ///     Lista de padrões regex a serem compilados e adicionados ao conjunto.
    ///
    /// Examples
    /// --------
    /// >>> idp = IdentificadorPadroes()
    /// >>> idp.adicionar(['RUA', 'AV'])
    fn adicionar(&mut self, regexs: Vec<String>) {
        self.interno.adicionar(&regexs);
    }

    /// Verifica se alguma das regexes cadastradas corresponde ao valor.
    ///
    /// Parameters
    /// ----------
    /// valor : str
    ///     Texto a ser verificado.
    ///
    /// Returns
    /// -------
    /// bool
    ///     True se alguma regex corresponder, False caso contrário.
    ///
    /// Examples
    /// --------
    /// >>> idp = IdentificadorPadroes()
    /// >>> idp.adicionar(['RUA'])
    /// >>> idp.identificar('RUA AZUL')
    /// True
    /// >>> idp.identificar('AVENIDA')
    /// False
    fn identificar(&self, valor: &str) -> bool {
        self.interno.identificar(valor)
    }
}

/// Obtém o padronizador utilizado internamente pela função `padronizar_logradouros`.
/// Útil para adicionar padrões de substituição não incluídos originalmente.
#[pyfunction]
pub fn obter_padronizador_logradouros() -> Padronizador {
    Padronizador {
        interno: enderecobr_rs::logradouro::criar_padronizador_logradouros(),
    }
}

/// Obtém o padronizador utilizado internamente pela função `padronizar_numeros`.
/// Útil para adicionar padrões de substituição não incluídos originalmente.
#[pyfunction]
pub fn obter_padronizador_numeros() -> Padronizador {
    Padronizador {
        interno: enderecobr_rs::numero::criar_padronizador_numeros(),
    }
}

/// Obtém o padronizador utilizado internamente pela função `padronizar_bairros`.
/// Útil para adicionar padrões de substituição não incluídos originalmente.
#[pyfunction]
pub fn obter_padronizador_bairros() -> Padronizador {
    Padronizador {
        interno: enderecobr_rs::bairro::criar_padronizador_bairros(),
    }
}

/// Obtém o padronizador utilizado internamente pela função `padronizar_complementos`.
/// Útil para adicionar padrões de substituição não incluídos originalmente.
#[pyfunction]
pub fn obter_padronizador_complementos() -> Padronizador {
    Padronizador {
        interno: enderecobr_rs::complemento::criar_padronizador_complemento(),
    }
}

/// Obtém o padronizador utilizado internamente pela função `padronizar_tipo_logradouro`.
/// Útil para adicionar padrões de substituição não incluídos originalmente.
#[pyfunction]
pub fn obter_padronizador_tipos_logradouros() -> Padronizador {
    Padronizador {
        interno: enderecobr_rs::tipo_logradouro::criar_padronizador_tipo_logradouro(),
    }
}
