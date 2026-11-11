//! Segmentos do endereço e o espelho do enum `TipoSegmento` do Rust.

use pyo3::prelude::*;

use crate::endereco::Endereco;

/// Um trecho do endereço e o atributo a que ele corresponde.
///
/// Em geral os objetos vêm prontos de `segmentar_endereco`, mas dá para
/// montar um à mão — útil ao reidratar o resultado de
/// `EnderecoSegmentado.como_json` ou ao testar
/// código que só lê os segmentos.
///
/// Parameters
/// ----------
/// valor : str
///     Trecho do endereço, sem os separadores originais.
/// tipo : TipoSegmento
///     Atributo do trecho.
///
/// Attributes
/// ----------
/// valor : str
///     Trecho do endereço, sem os separadores originais.
/// tipo : TipoSegmento
///     Atributo do trecho. Em JSON/dump sai como o rótulo em minúsculas
///     (`logradouro`, `numero`, `complemento` etc.).
///
/// Examples
/// --------
/// >>> from enderecobr import SegmentoEndereco, TipoSegmento
/// >>> segmento = SegmentoEndereco('apt 301', TipoSegmento.Complemento)
/// >>> (segmento.valor, segmento.tipo)
/// ('apt 301', TipoSegmento.Complemento)
/// >>> segmento.valor = 'apt 302'
/// >>> segmento.tipo = TipoSegmento.Outro
/// >>> (segmento.valor, segmento.tipo)
/// ('apt 302', TipoSegmento.Outro)
#[pyclass(eq, skip_from_py_object, module = "enderecobr.enderecobr")]
#[derive(Clone, Debug, PartialEq)]
pub struct SegmentoEndereco {
    interno: enderecobr_rs::separador_endereco::SegmentoEndereco,
}

/// Tipo de informação que um trecho do endereço representa.
///
/// As variantes são exatamente as mesmas do enum `TipoSegmento` do Rust, na
/// mesma ordem, e cada uma se compara igual ao seu valor inteiro
/// (`TipoSegmento.Cep == 12`, `int(TipoSegmento.Cep) == 12`).
///
/// Variantes, na ordem do enum:
///
/// - `Logradouro`: Tipo de via + título + nome: `R ALCIDES CARNEIRO LEAL`, `ROD BR-116`.
/// - `Numero`: Numeração predial, inclusive quando ausente: `71`, `S/N`.
/// - `Complemento`: Unidade interna do imóvel, tipo e valor juntos: `APTO 104`, `BL 4`.
/// - `Empreendimento`: Lugar nomeado: prédio, condomínio, conjunto, loteamento ou o próprio estabelecimento que ocupa o endereço: `ED MANAGUA`, `COND PALM VILLAGE`.
/// - `Parcela`: Identificador cadastral do terreno (uma `gleba` pode conter uma `quadra` que pode conter um `lote`): `QD 34 LOTE 17`.
/// - `QuilometragemVia`: Quilometragem em rodovia, onde o número é a posição ao longo da via: `KM 304`.
/// - `Referencia`: Trecho que aponta para outro endereço ou lugar: `ESQUINA COM AV BOA VIAGEM`.
/// - `PontoReferencia`: Referente de uma referência que não é via, lugar nem feição natural: `CLUBE`, `CASA DE GRACIENE`.
/// - `Denominacao`: Nome atual ou antigo da via ou do lugar: `ANTIGA RUA B`.
/// - `Localidade`: Localidade, bairro, distrito, vila ou zona: `PINA`, `ZONA RURAL`.
/// - `NucleoRural`: Cabeça + nome de lugar rural: `POVOADO AGUA PRETA`, `SITIO MIRADOR`, `ALDEIA X`. Especialização de `localidade`.
/// - `RecursoNatural`: Feição natural nomeada, onde quer que apareça: `RIO`, `CORREGO`, `LAGOA`, `MORRO`, `SERRA`, `ILHA`.
/// - `Cep`: Código de endereçamento postal.
/// - `Municipio`: Município.
/// - `Uf`: Unidade federativa.
/// - `Cadastro`: Código de cadastro do imóvel ou da unidade: `RI 16.282`, `MAT. 219.747`.
/// - `Ruido`: Token solto sem valor: pontuação, separador, id de processo vazado, lat/lon.
/// - `Outro`: Conteúdo que não cabe em nenhum outro tipo — inclusive rótulo que ainda não tem variante própria.
///
/// Examples
/// --------
/// >>> from enderecobr import TipoSegmento, SegmentoEndereco
/// >>> segmento = SegmentoEndereco('123', TipoSegmento.Numero)
/// >>> segmento.tipo == TipoSegmento.Numero
/// True
#[pyclass(eq, eq_int, from_py_object, module = "enderecobr.enderecobr")]
#[derive(Clone, Copy, Debug, PartialEq)]
pub enum TipoSegmento {
    Logradouro,
    Numero,
    Complemento,
    Empreendimento,
    Parcela,
    QuilometragemVia,
    Referencia,
    PontoReferencia,
    Denominacao,
    Localidade,
    NucleoRural,
    RecursoNatural,
    Cep,
    Municipio,
    Uf,
    Cadastro,
    Ruido,
    Outro,
}

impl TipoSegmento {
    /// Nome de cada variante, na ordem de declaração. É o `name` que o Python vê,
    /// equivalente ao de um `enum.IntEnum`.
    pub(crate) const NOMES: [&str; 18] = [
        "Logradouro",
        "Numero",
        "Complemento",
        "Empreendimento",
        "Parcela",
        "QuilometragemVia",
        "Referencia",
        "PontoReferencia",
        "Denominacao",
        "Localidade",
        "NucleoRural",
        "RecursoNatural",
        "Cep",
        "Municipio",
        "Uf",
        "Cadastro",
        "Ruido",
        "Outro",
    ];
}

// Não é um `enum.Enum` de verdade (o pyo3 não herda disso), mas expõe `name` e
// `value` para que o stub possa ser declarado como `enum.IntEnum` sem mentir.
#[pymethods]
impl TipoSegmento {
    #[getter]
    fn name(&self) -> &'static str {
        Self::NOMES[*self as usize]
    }

    #[getter]
    fn value(&self) -> i32 {
        *self as i32
    }

    /// Todas as variantes, na ordem de declaração do enum.
    ///
    /// É o equivalente a iterar o enum no Rust: serve para montar tabelas de
    /// rótulos, validar entrada ou varrer os tipos sem conhecê-los de antemão.
    ///
    /// Returns
    /// -------
    /// list of TipoSegmento
    ///     As 18 variantes, na ordem em que o modelo as emite.
    ///
    /// Examples
    /// --------
    /// >>> len(TipoSegmento.todos())
    /// 18
    /// >>> TipoSegmento.todos()[0]
    /// TipoSegmento.Logradouro
    #[staticmethod]
    fn todos() -> Vec<TipoSegmento> {
        // Fonte única: a lista do Rust, convertida pelo mesmo `From` do resto.
        enderecobr_rs::separador_endereco::TipoSegmento::TODOS
            .iter()
            .map(|tipo| TipoSegmento::from(*tipo))
            .collect()
    }
}

/// Texto entre aspas simples, do jeito que o Python mostra em `repr`.
fn entre_aspas(texto: &str) -> String {
    format!("'{}'", texto.replace('\\', "\\\\").replace('\'', "\\'"))
}

/// Probabilidade com até quatro casas, sem zeros à direita.
fn formatar_probabilidade(valor: f64) -> String {
    let mut texto = format!("{valor:.4}");
    while texto.ends_with('0') {
        texto.pop();
    }
    if texto.ends_with('.') {
        texto.push('0');
    }
    texto
}

/// `SegmentoEndereco(...)`, com a probabilidade só quando ela existe.
fn repr_de_segmento(segmento: &enderecobr_rs::separador_endereco::SegmentoEndereco) -> String {
    let tipo = TipoSegmento::from(segmento.tipo);
    let mut repr = format!(
        "SegmentoEndereco(valor={}, tipo=TipoSegmento.{}",
        entre_aspas(&segmento.valor),
        TipoSegmento::NOMES[tipo as usize]
    );
    if let Some(probabilidade) = segmento.probabilidade {
        repr.push_str(&format!(
            ", probabilidade={}",
            formatar_probabilidade(probabilidade)
        ));
    }
    repr.push(')');
    repr
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
                probabilidade: None,
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

    /// Probabilidade de o trecho estar com o tipo previsto, entre 0 e 1.
    ///
    /// Só vem preenchida quando a segmentação pediu as probabilidades
    /// (`com_probabilidade=True`); nos outros casos é `None`.
    #[getter]
    fn probabilidade(&self) -> Option<f64> {
        self.interno.probabilidade
    }

    #[setter]
    fn set_valor(&mut self, valor: String) {
        self.interno.valor = valor;
    }

    fn __repr__(&self) -> String {
        repr_de_segmento(&self.interno)
    }
}

/// Resultado da segmentação de um endereço.
///
/// Attributes
/// ----------
/// segmentos : list of SegmentoEndereco
///     Segmentos na ordem em que aparecem no texto original.
///
/// Examples
/// --------
/// Separar primeiro e agrupar depois, inspecionando os trechos no meio:
///
/// >>> seg = enderecobr.segmentar_endereco('av n sra copacabana, 123')  # doctest: +SKIP
/// >>> [(s.valor, s.tipo) for s in seg.segmentos]  # doctest: +SKIP
/// [('av n sra copacabana', TipoSegmento.Logradouro), ('123', TipoSegmento.Numero)]
/// >>> seg.como_endereco().logradouro  # doctest: +SKIP
/// 'AVENIDA NOSSA SENHORA COPACABANA'
#[pyclass(frozen, eq, skip_from_py_object, module = "enderecobr.enderecobr")]
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

    /// Probabilidade de a rotulagem inteira estar correta.
    ///
    /// Cai com o tamanho do endereço: para comparar endereços de tamanhos
    /// diferentes, use `confianca`. `None` quando a segmentação não pediu as
    /// probabilidades.
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

    fn __repr__(&self) -> String {
        let mut repr = String::from("EnderecoSegmentado(segmentos=[");
        for segmento in &self.interno.segmentos {
            repr.push_str("\n    ");
            repr.push_str(&repr_de_segmento(segmento));
            repr.push(',');
        }
        repr.push(if self.interno.segmentos.is_empty() {
            ']'
        } else {
            '\n'
        });
        if !self.interno.segmentos.is_empty() {
            repr.push(']');
        }
        if let Some(probabilidade) = self.interno.probabilidade {
            repr.push_str(&format!(
                ", probabilidade={}",
                formatar_probabilidade(probabilidade)
            ));
        }
        if let Some(confianca) = self.interno.confianca {
            repr.push_str(&format!(
                ", confianca={}",
                formatar_probabilidade(confianca)
            ));
        }
        repr.push(')');
        repr
    }

    /// Serializa os segmentos em JSON.
    ///
    /// Cada segmento vira `{"valor": ..., "tipo": ...}`, com o tipo como
    /// rótulo em minúsculas (`logradouro`, `numero`, `complemento` etc.).
    /// É o formato indicado para guardar o resultado da segmentação: é compacto
    /// e independente do texto original.
    ///
    /// Returns
    /// -------
    /// str
    ///     JSON no formato `{"segmentos": [...]}`.
    ///
    /// Examples
    /// --------
    /// >>> seg = enderecobr.segmentar_endereco('av n sra copacabana, 123')  # doctest: +SKIP
    /// >>> seg.como_json()  # doctest: +SKIP
    /// '{"segmentos":[{"valor":"av n sra copacabana","tipo":"logradouro"},{"valor":"123","tipo":"numero"}]}'
    fn como_json(&self) -> String {
        self.interno.como_json()
    }

    /// Agrupa os segmentos nos campos de um `Endereco`.
    ///
    /// É a segunda metade do que `estruturar_endereco` faz: cada trecho vai
    /// para o campo que o seu tipo indica, na ordem em que aparece. Serve para
    /// quem quer guardar os segmentos (ver `como_json`) e só depois montar o
    /// endereço, ou para trocar um segmento antes de agrupar.
    ///
    /// Parameters
    /// ----------
    /// padronizar : bool, optional
    ///     Se `True` (padrão), os campos resultantes passam pelas funções de
    ///     padronização.
    ///
    /// Returns
    /// -------
    /// Endereco
    ///     Endereço com os campos que os segmentos permitiram preencher.
    ///
    /// Examples
    /// --------
    /// >>> seg = enderecobr.segmentar_endereco('av n sra copacabana, 123')  # doctest: +SKIP
    /// >>> seg.como_endereco(padronizar=False).logradouro  # doctest: +SKIP
    /// 'av n sra copacabana'
    #[pyo3(signature = (padronizar = true))]
    fn como_endereco(&self, padronizar: bool) -> Endereco {
        self.interno.como_endereco(padronizar).into()
    }
}

impl From<enderecobr_rs::separador_endereco::TipoSegmento> for TipoSegmento {
    fn from(interno: enderecobr_rs::separador_endereco::TipoSegmento) -> Self {
        use enderecobr_rs::separador_endereco::TipoSegmento as Rs;
        match interno {
            Rs::Logradouro => TipoSegmento::Logradouro,
            Rs::Numero => TipoSegmento::Numero,
            Rs::Complemento => TipoSegmento::Complemento,
            Rs::Empreendimento => TipoSegmento::Empreendimento,
            Rs::Parcela => TipoSegmento::Parcela,
            Rs::QuilometragemVia => TipoSegmento::QuilometragemVia,
            Rs::Referencia => TipoSegmento::Referencia,
            Rs::PontoReferencia => TipoSegmento::PontoReferencia,
            Rs::Denominacao => TipoSegmento::Denominacao,
            Rs::Localidade => TipoSegmento::Localidade,
            Rs::NucleoRural => TipoSegmento::NucleoRural,
            Rs::RecursoNatural => TipoSegmento::RecursoNatural,
            Rs::Cep => TipoSegmento::Cep,
            Rs::Municipio => TipoSegmento::Municipio,
            Rs::Uf => TipoSegmento::Uf,
            Rs::Cadastro => TipoSegmento::Cadastro,
            Rs::Ruido => TipoSegmento::Ruido,
            Rs::Outro => TipoSegmento::Outro,
        }
    }
}

impl From<TipoSegmento> for enderecobr_rs::separador_endereco::TipoSegmento {
    fn from(espelho: TipoSegmento) -> Self {
        use enderecobr_rs::separador_endereco::TipoSegmento as Rs;
        match espelho {
            TipoSegmento::Logradouro => Rs::Logradouro,
            TipoSegmento::Numero => Rs::Numero,
            TipoSegmento::Complemento => Rs::Complemento,
            TipoSegmento::Empreendimento => Rs::Empreendimento,
            TipoSegmento::Parcela => Rs::Parcela,
            TipoSegmento::QuilometragemVia => Rs::QuilometragemVia,
            TipoSegmento::Referencia => Rs::Referencia,
            TipoSegmento::PontoReferencia => Rs::PontoReferencia,
            TipoSegmento::Denominacao => Rs::Denominacao,
            TipoSegmento::Localidade => Rs::Localidade,
            TipoSegmento::NucleoRural => Rs::NucleoRural,
            TipoSegmento::RecursoNatural => Rs::RecursoNatural,
            TipoSegmento::Cep => Rs::Cep,
            TipoSegmento::Municipio => Rs::Municipio,
            TipoSegmento::Uf => Rs::Uf,
            TipoSegmento::Cadastro => Rs::Cadastro,
            TipoSegmento::Ruido => Rs::Ruido,
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

/// Junta um endereço já segmentado nos campos de `Endereco`, sem rodar o modelo
/// de novo.
///
/// É o mesmo que `EnderecoSegmentado.como_endereco`, na forma de função — útil
/// quando a segmentação vem de outro lugar e você só quer estruturá-la.
///
/// Parameters
/// ----------
/// segmentado : EnderecoSegmentado
///     Resultado de `segmentar_endereco` ou `SeparadorEndereco.segmentar`.
/// padronizar : bool, optional
///     Se `True` (padrão), passa os campos pelas funções de padronização.
///
/// Returns
/// -------
/// Endereco
///     Endereço com os campos encontrados.
///
/// Examples
/// --------
/// >>> seg = enderecobr.segmentar_endereco('av n sra copacabana, 123')  # doctest: +SKIP
/// >>> enderecobr.estruturar_segmentos(seg).numero  # doctest: +SKIP
/// '123'
#[pyfunction]
#[pyo3(signature = (segmentado, padronizar = true))]
pub fn estruturar_segmentos(segmentado: &EnderecoSegmentado, padronizar: bool) -> Endereco {
    segmentado.interno.como_endereco(padronizar).into()
}
