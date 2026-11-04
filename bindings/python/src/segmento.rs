//! Segmentos do endereço e o espelho do enum `TipoSegmento` do Rust.

use pyo3::prelude::*;

/// Um trecho do endereço e o atributo a que ele corresponde.
///
/// Em geral os objetos vêm prontos de :func:`segmentar_endereco`, mas dá para
/// montar um à mão — útil ao reidratar um ``segmento_como_json`` ou ao testar
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
/// (``TipoSegmento.Cep == 14``, ``int(TipoSegmento.Cep) == 14``).
///
/// Variantes, na ordem do enum:
///
/// - [Logradouro][enderecobr.TipoSegmento.Logradouro]: Tipo de via + título + nome: `R ALCIDES CARNEIRO LEAL`, `ROD BR-116`.
/// - [LogradouroInterno][enderecobr.TipoSegmento.LogradouroInterno]: Via ou área interna de um empreendimento, fora do arruamento oficial.
/// - [Numero][enderecobr.TipoSegmento.Numero]: Numeração predial, inclusive quando ausente: `71`, `S/N`.
/// - [ModificadorNumero][enderecobr.TipoSegmento.ModificadorNumero]: Sufixo ou marcador preso ao número: `A`, `504-B1`, `POSTE`.
/// - [Complemento][enderecobr.TipoSegmento.Complemento]: Unidade interna do imóvel, tipo e valor juntos: `APTO 104`, `BL 4`.
/// - [Empreendimento][enderecobr.TipoSegmento.Empreendimento]: Lugar nomeado: prédio, condomínio, conjunto, loteamento ou o próprio estabelecimento que ocupa o endereço: `ED MANAGUA`, `COND PALM VILLAGE`.
/// - [Parcela][enderecobr.TipoSegmento.Parcela]: Identificador cadastral do terreno (uma `gleba` pode conter uma `quadra` que pode conter um `lote`): `QD 34 LOTE 17`.
/// - [QuilometragemVia][enderecobr.TipoSegmento.QuilometragemVia]: Quilometragem em rodovia, onde o número é a posição ao longo da via: `KM 304`.
/// - [Referencia][enderecobr.TipoSegmento.Referencia]: Trecho que aponta para outro endereço ou lugar: `ESQUINA COM AV BOA VIAGEM`.
/// - [PontoReferencia][enderecobr.TipoSegmento.PontoReferencia]: Referente de uma referência que não é via, lugar nem feição natural: `CLUBE`, `CASA DE GRACIENE`.
/// - [Denominacao][enderecobr.TipoSegmento.Denominacao]: Nome atual ou antigo da via ou do lugar: `ANTIGA RUA B`.
/// - [Localidade][enderecobr.TipoSegmento.Localidade]: Localidade, bairro, distrito, vila ou zona: `PINA`, `ZONA RURAL`.
/// - [NucleoRural][enderecobr.TipoSegmento.NucleoRural]: Cabeça + nome de lugar rural: `POVOADO AGUA PRETA`, `SITIO MIRADOR`, `ALDEIA X`. Especialização de `localidade`.
/// - [RecursoNatural][enderecobr.TipoSegmento.RecursoNatural]: Feição natural nomeada, onde quer que apareça: `RIO`, `CORREGO`, `LAGOA`, `MORRO`, `SERRA`, `ILHA`.
/// - [Cep][enderecobr.TipoSegmento.Cep]: Código de endereçamento postal.
/// - [Municipio][enderecobr.TipoSegmento.Municipio]: Município.
/// - [Uf][enderecobr.TipoSegmento.Uf]: Unidade federativa.
/// - [Cadastro][enderecobr.TipoSegmento.Cadastro]: Código de cadastro do imóvel ou da unidade: `RI 16.282`, `MAT. 219.747`.
/// - [Ruido][enderecobr.TipoSegmento.Ruido]: Token solto sem valor: pontuação, separador, id de processo vazado, lat/lon.
/// - [Outro][enderecobr.TipoSegmento.Outro]: Conteúdo que não cabe em nenhum outro tipo — inclusive rótulo que ainda não tem variante própria.
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
    LogradouroInterno,
    Numero,
    ModificadorNumero,
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
    pub(crate) const NOMES: [&str; 20] = [
        "Logradouro",
        "LogradouroInterno",
        "Numero",
        "ModificadorNumero",
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

/// Resultado da segmentação de um endereço.
///
/// Attributes
/// ----------
/// segmentos : list of SegmentoEndereco
///     Segmentos na ordem em que aparecem no texto original.
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
            TipoSegmento::LogradouroInterno => Rs::LogradouroInterno,
            TipoSegmento::Numero => Rs::Numero,
            TipoSegmento::ModificadorNumero => Rs::ModificadorNumero,
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
