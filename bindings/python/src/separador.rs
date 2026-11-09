//! `SeparadorEndereco`: modelo próprio, mais as funções que usam o modelo padrão.

use std::path::PathBuf;

use pyo3::exceptions::PyRuntimeError;
use pyo3::prelude::*;

use crate::endereco::Endereco;
use crate::segmento::EnderecoSegmentado;

/// Segmentador probabilístico de endereços.
///
/// Diferente das funções de módulo, permite usar um arquivo de modelo próprio
/// em vez do modelo padrão. A instância nasce **sem modelo**: o construtor não lê nem baixa
/// nada do disco. Use o método estático `carregar` ou o método `carregar_modelo`
/// antes de `segmentar`. Depois de carregado, o separador não falha mais
/// ao segmentar.
///
/// Para usar o modelo padrão, obtenha o caminho com `obter_modelo` (resolve e
/// baixa, se necessário) ou com `obter_caminho_modelo` (apenas resolve) e
/// passe o retorno para `carregar`.
///
/// Examples
/// --------
/// Usando o modelo padrão, sem precisar saber onde ele fica:
///
/// >>> from enderecobr import SeparadorEndereco, obter_modelo
/// >>> sep = SeparadorEndereco.carregar(obter_modelo())  # doctest: +SKIP
/// >>> sep.segmentar('av n sra copacabana, 123').segmentos[0].tipo  # doctest: +SKIP
/// TipoSegmento.Logradouro
///
/// O construtor não carrega nada, o que permite criar a instância primeiro:
///
/// >>> sep = SeparadorEndereco()
/// >>> sep.carregar_modelo('/caminho/para/tagger.crf')  # doctest: +SKIP
/// >>> sep.segmentar('av n sra copacabana, 123').segmentos[0].valor  # doctest: +SKIP
/// 'av n sra copacabana'
#[pyclass(module = "enderecobr.enderecobr")]
pub struct SeparadorEndereco {
    interno: Option<enderecobr_rs::separador_endereco::SeparadorEndereco>,
}

#[pymethods]
impl SeparadorEndereco {
    #[new]
    fn novo() -> SeparadorEndereco {
        SeparadorEndereco { interno: None }
    }

    /// Cria um separador já carregado a partir de um arquivo de modelo.
    ///
    /// Parameters
    /// ----------
    /// caminho : str or pathlib.Path
    ///     Caminho do arquivo de modelo treinado.
    ///
    /// Returns
    /// -------
    /// SeparadorEndereco
    ///     Separador pronto para uso.
    ///
    /// Raises
    /// ------
    /// RuntimeError
    ///     Se o arquivo não existir, não puder ser lido ou não for um modelo válido.
    #[staticmethod]
    fn carregar(caminho: PathBuf) -> PyResult<SeparadorEndereco> {
        Ok(SeparadorEndereco {
            interno: Some(abrir_modelo(caminho)?),
        })
    }

    /// Carrega (ou substitui) o modelo desta instância, sem criar um objeto novo.
    ///
    /// Parameters
    /// ----------
    /// caminho : str or pathlib.Path
    ///     Caminho do arquivo de modelo treinado.
    ///
    /// Raises
    /// ------
    /// RuntimeError
    ///     Se o arquivo não existir, não puder ser lido ou não for um modelo válido.
    fn carregar_modelo(&mut self, caminho: PathBuf) -> PyResult<()> {
        self.interno = Some(abrir_modelo(caminho)?);
        Ok(())
    }

    /// Segmenta o endereço nas suas partes constituintes.
    ///
    /// Parameters
    /// ----------
    /// texto : str
    ///     Endereço bruto a ser segmentado.
    ///
    /// Returns
    /// -------
    /// EnderecoSegmentado
    ///     Segmentos encontrados e seus atributos.
    ///
    /// Raises
    /// ------
    /// RuntimeError
    ///     Se nenhum modelo tiver sido carregado antes da chamada.
    ///
    /// Notes
    /// -----
    /// O interpretador não é bloqueado durante a inferência: o GIL é liberado,
    ///   portanto outras threads do Python seguem rodando.
    ///
    /// Examples
    /// --------
    /// >>> sep = enderecobr.SeparadorEndereco.carregar('/caminho/para/tagger.crf')  # doctest: +SKIP
    /// >>> seg = sep.segmentar('av n sra copacabana, 123, apt 301')  # doctest: +SKIP
    /// >>> [s.valor for s in seg.segmentos]  # doctest: +SKIP
    /// ['av n sra copacabana', '123', 'apt 301']
    fn segmentar(&self, py: Python<'_>, texto: &str) -> PyResult<EnderecoSegmentado> {
        let separador = self.modelo()?;

        // A inferência é a parte cara: rodar sem o GIL libera as outras threads.
        Ok(py.detach(|| separador.segmentar(texto)).into())
    }

    /// Segmenta vários endereços de uma vez com o modelo desta instância.
    ///
    /// A saída mantém a ordem de entrada, e cada posição corresponde ao endereço
    /// de mesmo índice.
    ///
    /// Parameters
    /// ----------
    /// textos : iterable of str
    ///     Endereços brutos a serem segmentados.
    ///
    /// Returns
    /// -------
    /// list of EnderecoSegmentado
    ///     Um resultado por endereço, na mesma ordem da entrada.
    ///
    /// Raises
    /// ------
    /// RuntimeError
    ///     Se nenhum modelo tiver sido carregado antes da chamada.
    ///
    /// Notes
    /// -----
    /// O GIL é liberado durante o processamento do lote inteiro.
    ///
    /// Examples
    /// --------
    /// >>> sep = enderecobr.SeparadorEndereco.carregar('/caminho/para/tagger.crf')  # doctest: +SKIP
    /// >>> resultados = sep.segmentar_enderecos(['av n sra copacabana, 123'])  # doctest: +SKIP
    /// >>> resultados[0].segmentos[0].tipo  # doctest: +SKIP
    /// 'logradouro'
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

/// Resolve o caminho do modelo de padrão e garante que o arquivo exista,
/// baixando-o na primeira chamada.
///
/// Usa a mesma ordem de prioridade de `obter_caminho_modelo` e só baixa o
/// modelo quando o arquivo está ausente ou vazio. O download pode ser desativado
/// com a variável de ambiente `ENDERECOBR_MODELO_SEM_DOWNLOAD=1` (útil em
/// CI).
///
/// Parameters
/// ----------
/// path_modelo : str or pathlib.Path or None, optional
///     Arquivo ou diretório do modelo. Informado, tem prioridade sobre a
///     variável de ambiente e sobre o cache.
///
/// Returns
/// -------
/// pathlib.Path
///     Caminho do arquivo `.crf`, já existente.
///
/// Raises
/// ------
/// RuntimeError
///     Se o diretório de destino não puder ser criado, o download falhar ou o
///     arquivo não puder ser gravado.
///
/// Examples
/// --------
/// >>> from enderecobr import SeparadorEndereco, obter_modelo
/// >>> sep = SeparadorEndereco.carregar(obter_modelo())  # doctest: +SKIP
/// >>> sep.segmentar('av n sra copacabana, 123').segmentos[0].tipo  # doctest: +SKIP
/// 'logradouro'
///
/// Notes
/// -----
/// - Faz uma requisição HTTP (timeout de 60 s) apenas quando precisa baixar e
///   libera o GIL durante a operação.
/// - O caminho devolvido pode ser passado direto para `SeparadorEndereco.carregar`.
#[pyfunction]
#[pyo3(signature = (path_modelo = None))]
pub fn obter_modelo(py: Python<'_>, path_modelo: Option<PathBuf>) -> PyResult<PathBuf> {
    // O download é bloqueante (até 60 s): não segurar o GIL enquanto isso.
    py.detach(|| enderecobr_rs::separador_endereco::obter_modelo(path_modelo.as_deref()))
        .map_err(crate::erro_de_modelo)
}

/// Resolve o caminho do modelo sem gravar nada no disco.
///
/// Segue esta ordem de prioridade:
///
/// 1. `path_modelo`, quando informado e não vazio;
/// 2. a variável de ambiente `ENDERECOBR_MODELO`, quando definida e não vazia;
/// 3. o diretório de cache do sistema operacional (`~/.cache/...` no Linux,
///    `~/Library/Caches` no macOS, `%LOCALAPPDATA%` no Windows), no caminho
///    `enderecobr_rs/<versão do modelo>/tagger.crf`.
///
/// Se o valor resolvido for um diretório (ou terminar em `/`), o subdiretório
/// da versão do modelo é acrescentado; se for um arquivo, ele é usado como está.
///
/// Parameters
/// ----------
/// path_modelo : str or pathlib.Path or None, optional
///     Arquivo ou diretório do modelo. Informado, tem prioridade sobre a
///     variável de ambiente e sobre o cache.
///
/// Returns
/// -------
/// pathlib.Path
///     Caminho do arquivo que seria usado. O arquivo pode não existir.
///
/// Raises
/// ------
/// RuntimeError
///     Se nem o argumento nem `ENDERECOBR_MODELO` forem informados e o
///     diretório de cache do sistema operacional não estiver disponível.
///
/// Examples
/// --------
/// >>> enderecobr.obter_caminho_modelo('/tmp/modelos/').name
/// 'tagger.crf'
/// >>> enderecobr.obter_caminho_modelo('/tmp/meu_modelo.crf').as_posix()
/// '/tmp/meu_modelo.crf'
///
/// Notes
/// -----
/// - Não acessa o disco nem a rede: só calcula o caminho.
/// - É útil para inspecionar qual arquivo `obter_modelo` usaria, antes de
///   baixar qualquer coisa.
#[pyfunction]
#[pyo3(signature = (path_modelo = None))]
pub fn obter_caminho_modelo(path_modelo: Option<PathBuf>) -> PyResult<PathBuf> {
    enderecobr_rs::separador_endereco::obter_caminho_modelo(path_modelo.as_deref())
        .map_err(crate::erro_de_modelo)
}

/// Segmenta um endereço usando o modelo padrão, compartilhado entre chamadas.
///
/// Usa o modelo resolvido por `ENDERECOBR_MODELO` ou o cache do sistema
/// (baixando-o na primeira chamada, se necessário). Para usar um modelo próprio,
/// prefira `SeparadorEndereco`.
///
/// Para saber (ou controlar) qual arquivo é esse, veja `obter_caminho_modelo`
/// (resolve o caminho sem tocar no disco) e `obter_modelo` (resolve e baixa).
///
/// Parameters
/// ----------
/// endereco : str
///     Endereço bruto a ser segmentado.
///
/// Returns
/// -------
/// EnderecoSegmentado
///     Segmentos encontrados e seus atributos.
///
/// Raises
/// ------
/// RuntimeError
///     Se o modelo padrão não puder ser obtido ou carregado.
///
/// Examples
/// --------
/// >>> seg = enderecobr.segmentar_endereco('av n sra copacabana, 123')  # doctest: +SKIP
/// >>> [(s.valor, s.tipo) for s in seg.segmentos]  # doctest: +SKIP
/// [('av n sra copacabana', TipoSegmento.Logradouro), ('123', TipoSegmento.Numero)]
///
/// Notes
/// -----
/// O GIL é liberado durante a inferência, então outras threads do Python
/// seguem rodando.
#[pyfunction]
pub fn segmentar_endereco(py: Python<'_>, endereco: &str) -> PyResult<EnderecoSegmentado> {
    let segmentado = py
        .detach(|| enderecobr_rs::tentar_segmentar_endereco(endereco))
        .map_err(crate::erro_de_modelo_padrao)?;
    Ok(segmentado.into())
}

/// Segmenta vários endereços de uma vez com o modelo padrão.
///
/// É a forma mais eficiente de processar uma lista ou uma coluna de endereços:
/// o modelo é carregado uma única vez e o interpretador não é bloqueado durante
/// o processamento.
///
/// A saída mantém a ordem de entrada, e cada posição corresponde ao endereço de
/// mesmo índice.
///
/// Parameters
/// ----------
/// enderecos : iterable of str
///     Endereços brutos a serem segmentados.
///
/// Returns
/// -------
/// list of EnderecoSegmentado
///     Um resultado por endereço, na mesma ordem da entrada.
///
/// Raises
/// ------
/// RuntimeError
///     Se o modelo padrão não puder ser obtido ou carregado.
///
/// Examples
/// --------
/// >>> resultados = enderecobr.segmentar_enderecos([  # doctest: +SKIP
/// ...     'av n sra copacabana, 123',
/// ...     'r das flores, 45, apt 12',
/// ... ])
/// >>> len(resultados)  # doctest: +SKIP
/// 2
#[pyfunction]
pub fn segmentar_enderecos(
    py: Python<'_>,
    enderecos: Vec<String>,
) -> PyResult<Vec<EnderecoSegmentado>> {
    let segmentados = py
        .detach(|| {
            let textos: Vec<&str> = enderecos.iter().map(String::as_str).collect();
            enderecobr_rs::tentar_segmentar_enderecos(&textos)
        })
        .map_err(crate::erro_de_modelo_padrao)?;
    Ok(segmentados
        .into_iter()
        .map(EnderecoSegmentado::from)
        .collect())
}

/// Segmenta o endereço e devolve os campos já separados em um `Endereco`.
///
/// Atalho para segmentar e depois agrupar os trechos nos campos do endereço.
/// Use `segmentar_endereco` quando quiser ver os trechos e seus tipos.
///
/// Parameters
/// ----------
/// endereco : str
///     Endereço bruto a ser estruturado.
/// padronizar : bool, optional
///     Se `True` (padrão), os campos resultantes passam pelas funções de
///     padronização.
///
/// Returns
/// -------
/// Endereco
///     Endereço com os campos encontrados.
///
/// Raises
/// ------
/// RuntimeError
///     Se o modelo padrão não puder ser obtido ou carregado.
///
/// Examples
/// --------
/// >>> end = enderecobr.estruturar_endereco('av n sra copacabana, 123')  # doctest: +SKIP
/// >>> end.numero  # doctest: +SKIP
/// '123'
#[pyfunction]
#[pyo3(signature = (endereco, padronizar = true))]
pub fn estruturar_endereco(py: Python<'_>, endereco: &str, padronizar: bool) -> PyResult<Endereco> {
    let estruturado = py
        .detach(|| enderecobr_rs::tentar_estruturar_endereco(endereco, padronizar))
        .map_err(crate::erro_de_modelo_padrao)?;
    Ok(estruturado.into())
}
