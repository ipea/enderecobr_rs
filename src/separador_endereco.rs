//!
//!# Funcionamento Resumido do Estruturador de Endereços
//!
//!Este módulo transforma uma linha de endereço em texto livre (como chega de um
//!cadastro qualquer) em um [`Endereco`] com campos separados. O pipeline tem
//!quatro etapas, cada uma detalhada em uma seção abaixo:
//!
//!1. **Tokenização**: o texto é quebrado em unidades atômicas (`tokens`);
//!2. **Rotulagem**: um modelo probabilístico atribui a cada token um rótulo
//!   que indica o tipo de informação e o papel no trecho;
//!3. **Agrupamento**: tokens rotulados em sequência viram trechos tipados
//!   ([`SegmentoEndereco`]);
//!4. **Estruturação**: os trechos são mapeados para os campos de um [`Endereco`]
//!   (`estruturacao`), com padronização opcional.
//!
//![`segmentar_endereco`] executa as três primeiras etapas e devolve os trechos;
//![`estruturar_endereco`] roda o pipeline completo e devolve o endereço pronto.
//!Ambas usam o modelo distribuído com o pacote, cuja obtenção (busca local,
//!download e cache) fica em [`modelo`]; [`SeparadorEndereco`] permite segmentar
//!com um arquivo de modelo próprio.
//!
//!O fluxo de uma chamada:
//!
//!```text
//!     ┌────────────────────────────────────────────────────────────────┐
//!     │ SQN 404 Bloco A APT 309, Asa Norte                             │
//!     └────────────────────────────────┬───────────────────────────────┘
//!                                      │ tokenização + rotulagem
//!                                      ▼
//!     ┌───────┬───────┬───────┬───────┬───────┬───────┬──┬──────┬──────┐
//!     │  SQN  │  404  │ Bloco │   A   │  APT  │  309  │, │ Asa  │Norte │
//!     ├───────┼───────┼───────┼───────┼───────┼───────┼──┼──────┼──────┤
//!     │ B_LOGR│ I_LOGR│ I_LOGR│ I_LOGR│ B_COMP│ I_COMP│O │B_LOC │I_LOC │
//!     └───────┴───────┴───────┴───────┴───────┴───────┴──┴──────┴──────┘
//!                                      │ agrupamento dos trechos
//!                                      ▼
//!     ┌─────────────────┐   ┌─────────────┐   ┌────────────┐
//!     │ SQN 404 Bloco A │   │ APT 309     │   │ Asa Norte  │
//!     ├─────────────────┤   ├─────────────┤   ├────────────┤
//!     │ logradouro      │   │ complemento │   │ localidade │
//!     └─────────────────┘   └─────────────┘   └────────────┘
//!                                      │  estruturação + padronização
//!                                      ▼
//!     ┌────────────────────────────────────────┐
//!     │  Logradouro:   SQN 404 BLOCO A         │
//!     │  Número:       —                       │
//!     │  Complemento:  APARTAMENTO 309         │
//!     │  Localidade:   ASA NORTE               │
//!     │  CEP:          —                       │
//!     └────────────────────────────────────────┘
//!```
//!
//!## Tokenização
//!A tokenização é o processo de quebrar um texto em unidades atômicas (os *tokens*) que
//!servem de entrada para o modelo. Neste projeto, optou-se por uma abordagem mais
//!simplista: um token é uma sequência de letras, uma sequência de números ou um único
//!caractere de pontuação/símbolo.
//!`"Rua das Flores 123,,apt101"` vira `["Rua", "das", "Flores", "123", ",", ",", "apt", "101"]`.
//!
//!A tokenização também devolve a posição de cada token no texto original, usada depois
//!para decidir se a junção de dois tokens leva espaço ou se eles vinham grudados.
//!
//!## Rotulagem dos tokens
//!Com os tokens prontos, um processo de classificação é executado sobre eles: um modelo
//!probabilístico atribui um rótulo a cada token, indicando ao mesmo tempo o tipo de
//!informação que ele contém e o papel dele dentro do trecho (se ele está iniciando ou continuando o trecho).
//!
//!### Rotulagem BIO
//!No esquema BIO, o prefixo do rótulo diz o papel do token no trecho e o sufixo diz o
//!tipo de informação. O modelo emite três formatos de rótulo:
//!
//!- `B_<tipo>`: inicia um trecho do tipo (ex.: `B_logradouro`);
//!- `I_<tipo>`: continua o trecho anterior, desde que seja do mesmo tipo;
//!- `O`: token que não pertence a nenhum campo (descartado).
//!
//!### Classes usadas
//!As classes de tipo são as variantes de [`TipoSegmento`], documentadas no próprio enum.
//!
//!Essas classes foram definidas desta forma pois torna as classes mais bem definidas e
//!permite o reuso do modelo no futuro em outras situações, simplesmente aprimorando
//!a etapa de estruturação para a situação específica do usuário, e sem depender de uma
//!nova coleta de dados.
//!
//!### Conditional Random Fields - CRF
//!Este é o modelo probabilístico utilizado atualmente. São modelos lineares que levam em conta a ordem das etiquetas: o rótulo de um dado token
//!depende dos rótulos de seus vizinhos, diferente de um classificador comum que rotularia
//!cada token isoladamente. Isso captura dependências locais, por exemplo, quando "309" vem depois de "APT", quase certamente estamos falando de uma continuação do complemento. O modelo é treinado fora desta
//!biblioteca com o crfsuite e distribuído como um arquivo `.crf`.
//!
//!## Agrupamento de trechos
//!Os tokens rotulados são reunidos em trechos ([`SegmentoEndereco`]): `B_<tipo>` abre
//!um novo trecho e `I_<tipo>` é anexado ao último, desde que o tipo bata — `I` de tipo
//!diferente ou sem trecho anterior é descartado, e `O` é ignorado. A posição original
//!de cada token decide a junção: com espaço antes no texto original, os valores são
//!unidos com espaço (`"APT 309"`); grudados, continuam grudados (`"504-B1"`).
//!
//!## Estruturação em endereço
//!Os trechos são distribuídos nos campos de um [`Endereco`] por heurísticas em
//!`estruturacao` (vide [`estruturar_segmentos`]): cada tipo de trecho tem campos
//!preferidos e o mapeamento pode olhar os trechos vizinhos. Como essas regras mudam
//!frequentemente, a referência exata é o próprio código, não esta documentação.
//!
//!O modelo cuida apenas da segmentação; com `padronizar = true`, cada campo resultante
//!passa depois pelo padronizador do seu tipo, baseado em expressões regulares.
//!
//!A obtenção do arquivo do modelo (busca, download e cache) fica em [`modelo`], e a
//!inferência em si (Viterbi e marginais) em [`crf`].
pub mod crf;
mod estruturacao;
pub mod features;
pub mod modelo;
pub mod vocabulario;

use std::{cell::RefCell, ops::Range, path::PathBuf, sync::LazyLock};

use serde::Serialize;
use strum::{Display, IntoStaticStr, VariantArray};

use crate::separador_endereco::crf::Tagger;

pub use crate::separador_endereco::estruturacao::estruturar_segmentos;
pub use crate::separador_endereco::modelo::obter_caminho_modelo;
#[cfg(feature = "download")]
pub use crate::separador_endereco::modelo::obter_modelo;

use crate::{endereco::Endereco, separador_endereco::features::ExtratorFeature};

/// Separador de endereços: divide um texto livre em partes (logradouro,
/// número, complemento, CEP etc.) com o auxílio de um modelo probabilístico.
///
/// Em geral não é preciso criar uma instância: [`segmentar_endereco`] e
/// [`estruturar_endereco`] já usam o modelo distribuído com o pacote.
/// Instancie apenas quando quiser trabalhar com um arquivo de modelo próprio.
pub struct SeparadorEndereco {
    /// Modelo usado na classificação dos trechos do endereço.
    pub modelo: crf::Modelo,
    /// Responsável por transformar o texto nos atributos lidos pelo modelo.
    pub extrator: ExtratorFeature,
}

/// O que pedir a uma segmentação.
///
/// ```
/// use enderecobr_rs::separador_endereco::OpcoesSegmentacao;
///
/// assert!(!OpcoesSegmentacao::sem_probabilidades().probabilidades);
/// assert!(OpcoesSegmentacao::com_probabilidades().probabilidades);
/// ```
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub struct OpcoesSegmentacao {
    /// Calcula a probabilidade de cada trecho, a probabilidade do endereço
    /// inteiro e a confiança por token, ao custo de cerca de 10% a mais de
    /// tempo. Sem isso os campos de probabilidade ficam vazios.
    pub probabilidades: bool,
}

impl OpcoesSegmentacao {
    /// Segmenta sem calcular probabilidades: o caminho mais rápido.
    pub fn sem_probabilidades() -> OpcoesSegmentacao {
        OpcoesSegmentacao::default()
    }

    /// Pede a probabilidade de cada trecho, a do endereço inteiro e a
    /// confiança por token, ao custo de cerca de 10% a mais de tempo.
    pub fn com_probabilidades() -> OpcoesSegmentacao {
        OpcoesSegmentacao {
            probabilidades: true,
        }
    }
}

/// O que pedir ao estruturar um endereço.
///
/// ```
/// use enderecobr_rs::separador_endereco::OpcoesEndereco;
///
/// let padrao = OpcoesEndereco::default();
/// assert!(padrao.padronizar);
/// assert!(!padrao.probabilidades);
///
/// let cru = padrao.sem_padronizar().com_probabilidades();
/// assert!(!cru.padronizar);
/// assert!(cru.probabilidades);
///
/// // Os quatro builders se sobrepõem de propósito, para qualquer ponto ser
/// // ponto de partida.
/// assert_eq!(cru.com_padronizar(), OpcoesEndereco::default().com_probabilidades());
/// assert_eq!(cru.sem_probabilidades(), padrao.sem_padronizar());
/// ```
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct OpcoesEndereco {
    /// Passa os campos encontrados pelas funções de padronização, que
    /// expandem abreviações, corrigem a caixa e normalizam números e CEP.
    pub padronizar: bool,
    /// Preenche as probabilidades do endereço, ao custo de cerca de 10% a mais
    /// de tempo. Sem isso, os campos de probabilidade ficam vazios.
    pub probabilidades: bool,
}

impl Default for OpcoesEndereco {
    /// O caminho comum: padroniza os campos e não calcula probabilidades.
    fn default() -> OpcoesEndereco {
        OpcoesEndereco {
            padronizar: true,
            probabilidades: false,
        }
    }
}

impl OpcoesEndereco {
    /// Mantém os campos como vieram da segmentação.
    pub fn sem_padronizar(self) -> OpcoesEndereco {
        OpcoesEndereco {
            padronizar: false,
            ..self
        }
    }

    /// Passa os campos pelas funções de padronização.
    pub fn com_padronizar(self) -> OpcoesEndereco {
        OpcoesEndereco {
            padronizar: true,
            ..self
        }
    }

    /// Pede as probabilidades do endereço, ao custo de cerca de 10% a mais de
    /// tempo.
    pub fn com_probabilidades(self) -> OpcoesEndereco {
        OpcoesEndereco {
            probabilidades: true,
            ..self
        }
    }

    /// Deixa os campos de probabilidade vazios.
    pub fn sem_probabilidades(self) -> OpcoesEndereco {
        OpcoesEndereco {
            probabilidades: false,
            ..self
        }
    }
}

/// Tipo de informação que um trecho do endereço representa.
///
/// As variantes espelham, uma a uma, os rótulos que o modelo probabilístico emite.
/// Rótulos sem variante própria caem em [`TipoSegmento::Outro`].
///
/// ```
/// use enderecobr_rs::separador_endereco::TipoSegmento;
///
/// assert_eq!(TipoSegmento::from("logradouro"), TipoSegmento::Logradouro);
/// assert_eq!(TipoSegmento::from("novo_rotulo"), TipoSegmento::Outro);
/// ```
#[derive(
    Serialize, Debug, PartialEq, Eq, Clone, Copy, Hash, Display, IntoStaticStr, VariantArray,
)]
#[serde(rename_all = "snake_case")]
#[strum(serialize_all = "snake_case")]
pub enum TipoSegmento {
    /// Tipo de via + título + nome: `R ALCIDES CARNEIRO LEAL`, `ROD BR-116`.
    Logradouro,
    /// Numeração predial, inclusive quando ausente: `71`, `S/N`.
    Numero,
    /// Unidade interna do imóvel, tipo e valor juntos: `APTO 104`, `BL 4`.
    Complemento,
    /// Lugar nomeado: prédio, condomínio, conjunto, loteamento ou o próprio
    /// estabelecimento que ocupa o endereço: `ED MANAGUA`, `COND PALM VILLAGE`.
    Empreendimento,
    /// Identificador cadastral do terreno (gleba ⊃ quadra ⊃ lote): `QD 34 LOTE 17`.
    Parcela,
    /// Quilometragem em rodovia, onde o número é a posição ao longo da via: `KM 304`.
    QuilometragemVia,
    /// Trecho que aponta para outro endereço ou lugar: `ESQUINA COM`.
    Referencia,
    /// Referente de uma referência que não é via, lugar nem feição natural:
    /// `CLUBE`, `CASA DE JOAO`. É uma categoria residual.
    PontoReferencia,
    /// Nome atual ou antigo da via ou do lugar: `ANTIGA RUA B`.
    Denominacao,
    /// Localidade, bairro, distrito, vila ou zona: `PINA`, `ZONA RURAL`.
    Localidade,
    /// Cabeça + nome de lugar rural: `POVOADO AGUA PRETA`, `SITIO MIRADOR`,
    /// `ALDEIA X`. Especialização de `localidade`.
    NucleoRural,
    /// Ponto de interesse natural, onde quer que apareça: `RIO`, `CORREGO`, `LAGOA`,
    /// `MORRO`, `SERRA`, `ILHA`.
    RecursoNatural,
    /// CEP.
    Cep,
    /// Município.
    Municipio,
    /// Unidade federativa.
    Uf,
    /// Código de cadastro do imóvel ou da unidade: `RI 16.282`, `MAT. 219.747`.
    Cadastro,
    /// Token solto sem valor: pontuação, separador, id de processo vazado, lat/lon.
    Ruido,
    /// Conteúdo que não cabe em nenhum outro tipo — inclusive rótulo que ainda
    /// não tem variante própria.
    #[strum(serialize = "outros")]
    #[serde(rename = "outros")]
    Outro,
}

impl TipoSegmento {
    /// Todas as variantes, na ordem de declaração.
    ///
    /// ```
    /// use enderecobr_rs::separador_endereco::TipoSegmento;
    ///
    /// let rotulos: Vec<&str> = TipoSegmento::TODOS.iter().map(|tipo| tipo.como_str()).collect();
    /// assert_eq!(rotulos[..3], ["logradouro", "numero", "complemento"]);
    /// ```
    pub const TODOS: &'static [TipoSegmento] = TipoSegmento::VARIANTS;

    /// Rótulo em minúsculas, igual ao usado na serialização e nos dumps do modelo.
    ///
    /// ```
    /// use enderecobr_rs::separador_endereco::TipoSegmento;
    ///
    /// assert_eq!(TipoSegmento::Cep.como_str(), "cep");
    /// ```
    pub fn como_str(self) -> &'static str {
        self.into()
    }
}

impl From<&str> for TipoSegmento {
    /// Converte os rótulos emitidos pelo modelo, de forma case insensitive,
    /// para o enum [`TipoSegmento`].
    ///
    /// Rótulos desconhecidos caem em [`TipoSegmento::Outro`] em vez de falhar:
    /// um modelo novo não deve derrubar a segmentação.
    ///
    /// ```
    /// use enderecobr_rs::separador_endereco::TipoSegmento;
    ///
    /// assert_eq!(TipoSegmento::from("PONTO_REFERENCIA"), TipoSegmento::PontoReferencia);
    /// assert_eq!(TipoSegmento::from("Localidade"), TipoSegmento::Localidade);
    /// ```
    fn from(rotulo: &str) -> Self {
        Self::TODOS
            .iter()
            .copied()
            .find(|tipo| tipo.como_str().eq_ignore_ascii_case(rotulo))
            .unwrap_or(TipoSegmento::Outro)
    }
}

/// Um trecho do endereço junto com o tipo de informação que ele representa.
#[derive(Serialize, Debug, PartialEq, Clone)]
pub struct SegmentoEndereco {
    pub valor: String,
    pub tipo: TipoSegmento,
    /// Probabilidade de a rotulagem deste trecho estar correta, quando pedida.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub probabilidade: Option<f64>,
}

impl SegmentoEndereco {
    /// Cria um trecho ainda sem probabilidade calculada.
    pub fn novo(valor: impl Into<String>, tipo: TipoSegmento) -> SegmentoEndereco {
        SegmentoEndereco {
            valor: valor.into(),
            tipo,
            probabilidade: None,
        }
    }
}

/// Resultado da segmentação: os trechos identificados, na ordem em que aparecem
/// no texto original.
///
/// ```
/// use enderecobr_rs::separador_endereco::{
///     segmento_como_json, EnderecoSegmentado, SegmentoEndereco, TipoSegmento,
/// };
///
/// let segmentado = EnderecoSegmentado::novo(vec![
///     SegmentoEndereco::novo("av atlantica", TipoSegmento::Logradouro),
///     SegmentoEndereco::novo("123", TipoSegmento::Numero),
/// ]);
///
/// assert_eq!(
///     segmento_como_json(&segmentado),
///     r#"{"segmentos":[{"valor":"av atlantica","tipo":"logradouro"},{"valor":"123","tipo":"numero"}]}"#
/// );
/// ```
#[derive(Serialize, Debug, PartialEq, Clone, Default)]
pub struct EnderecoSegmentado {
    /// Trechos identificados no endereço.
    pub segmentos: Vec<SegmentoEndereco>,
    /// Probabilidade de a rotulagem do endereço inteiro estar correta, quando
    /// pedida (vide [`OpcoesSegmentacao::com_probabilidades`]).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub probabilidade: Option<f64>,
    /// Certeza média por trecho, entre 0 e 1: a média geométrica das
    /// probabilidades de cada token, normalizada pelo tamanho do endereço —
    /// diferente do campo [`Self::probabilidade`], que cai com o tamanho.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub confianca: Option<f64>,
}

impl SeparadorEndereco {
    /// Cria um separador a partir de um arquivo de modelo já treinado.
    ///
    /// Devolve erro quando o arquivo não existe, não é um modelo válido ou não
    /// consegue ser usado para classificar. Depois de criado, o separador não
    /// falha mais ao segmentar: a única falha restante seria falta de memória,
    /// que já é testada aqui.
    pub fn carregar(caminho: PathBuf) -> Result<SeparadorEndereco, String> {
        let modelo = crf::Modelo::carregar(&caminho)?;

        let separador = SeparadorEndereco {
            modelo,
            extrator: ExtratorFeature::novo(None),
        };

        // Cria um tagger de teste e o descarta: garante já na carga que o modelo
        // é utilizável, para a segmentação em si não ter como falhar.
        drop(separador.novo_tagger());

        Ok(separador)
    }

    /// Junta os tokens em segmentos, seguindo os rótulos devolvidos pelo modelo.
    /// Devolve, junto, a faixa de tokens de cada segmento, na mesma ordem.
    fn montar_segmentos(
        &self,
        original: &str,
        tokens: &[&str],
        tags: &[String],
        offsets: &[usize],
    ) -> (Vec<SegmentoEndereco>, Vec<Range<usize>>) {
        let mut segmentos = Vec::with_capacity(4);
        let mut faixas: Vec<Range<usize>> = Vec::with_capacity(4);
        for (indice, ((tok, tok_tipo), offset)) in tokens.iter().zip(tags).zip(offsets).enumerate()
        {
            // Rótulos são "B_<TIPO>", "I_<TIPO>" ou "O": comparar o byte do BIO
            // evita comparações de string no hot path.
            let Some((bio, tipo)) = tok_tipo.split_once('_') else {
                continue; // "O"
            };

            let tipo = TipoSegmento::from(tipo);
            match bio.as_bytes().first().copied() {
                Some(b'B') => {
                    segmentos.push(SegmentoEndereco::novo(*tok, tipo));
                    faixas.push(indice..indice + 1);
                }
                Some(b'I') => {
                    let Some(ultimo_segmento) = segmentos.last_mut() else {
                        continue;
                    };
                    // Comparação de enum: não aloca nem depende da caixa do rótulo.
                    if ultimo_segmento.tipo != tipo {
                        continue;
                    }
                    let tem_espaco = offset
                        .checked_sub(1)
                        .and_then(|anterior| original.as_bytes().get(anterior))
                        .is_some_and(u8::is_ascii_whitespace);
                    if tem_espaco {
                        ultimo_segmento.valor.push(' ');
                    }
                    ultimo_segmento.valor.push_str(tok);
                    if let Some(faixa) = faixas.last_mut() {
                        faixa.end = indice + 1;
                    }
                }
                _ => continue,
            }
        }

        (segmentos, faixas)
    }

    /// Segmenta um endereço com este separador. Vide [`segmentar_endereco`].
    pub fn segmentar(&self, texto: &str, opcoes: &OpcoesSegmentacao) -> EnderecoSegmentado {
        let mut tagger = self.novo_tagger();
        self.processar(&mut tagger, texto, opcoes)
    }

    /// Segmenta vários endereços com este separador, reaproveitando o mesmo
    /// tagger entre eles (mais rápido que chamar [`segmentar`](Self::segmentar)
    /// em sequência).
    ///
    /// A saída mantém a ordem da entrada.
    pub fn segmentar_enderecos(
        &self,
        textos: &[&str],
        opcoes: &OpcoesSegmentacao,
    ) -> Vec<EnderecoSegmentado> {
        let mut tagger = self.novo_tagger();
        textos
            .iter()
            .map(|texto| self.processar(&mut tagger, texto, opcoes))
            .collect()
    }

    /// Cria um tagger para este modelo.
    fn novo_tagger(&self) -> Tagger<'_> {
        self.modelo.novo_tagger()
    }

    /// Pipeline completo (tokenização, features, modelo e remontagem dos
    /// segmentos), usando um tagger já pronto para ele poder ser reaproveitado.
    ///
    /// Com [`OpcoesSegmentacao::probabilidades`], cada trecho e o endereço
    /// inteiro saem com as probabilidades preenchidas.
    fn processar(
        &self,
        tagger: &mut Tagger<'_>,
        texto: &str,
        opcoes: &OpcoesSegmentacao,
    ) -> EnderecoSegmentado {
        let (tokens, offsets) = self.extrator.tokenize(texto);
        if tokens.is_empty() {
            return EnderecoSegmentado::default();
        }
        let features = self.extrator.tokens2features(&tokens);

        if !opcoes.probabilidades {
            let tags = tagger.rotular(&features);
            let (segmentos, _) = self.montar_segmentos(texto, &tokens, &tags, &offsets);
            return EnderecoSegmentado::novo(segmentos);
        }

        let estimativa = tagger.rotular_com_probabilidades(&features);
        let (mut segmentos, faixas) =
            self.montar_segmentos(texto, &tokens, &estimativa.rotulos, &offsets);
        let probabilidades = tagger.probabilidade_trecho(&faixas);
        for (segmento, probabilidade) in segmentos.iter_mut().zip(probabilidades) {
            segmento.probabilidade = Some(probabilidade);
        }

        EnderecoSegmentado {
            segmentos,
            probabilidade: Some(estimativa.probabilidade),
            confianca: Some(estimativa.confianca),
        }
    }
}

// Em Rust, a constant é criada durante a compilação, então só posso chamar funções muito restritas
// quando uso `const`. Nesse caso,  como tenho uma construção complexa da struct `Padronizador`,
// tenho que usar static com inicialização Lazy (o LazyLock aqui previne condições de corrida).
// O `Result` guarda a falha (modelo indisponível) para que ela vire um erro comum em
// vez de um panic na primeira chamada.
static SEPARADOR: LazyLock<Result<SeparadorEndereco, String>> =
    LazyLock::new(|| SeparadorEndereco::carregar(modelo::obter_modelo_padrao(None)?));

/// Devolve o separador padrão, carregado na primeira chamada.
fn separador_padrao() -> Result<&'static SeparadorEndereco, String> {
    SEPARADOR.as_ref().map_err(|erro| erro.clone())
}

thread_local! {
    /// Um `Tagger` reaproveitado por thread.
    static TAGGER: RefCell<Option<Tagger<'static>>> = const { RefCell::new(None) };
}

/// Executa `f` com o tagger da thread atual, criando-o na primeira chamada.
fn com_tagger<R>(
    separador: &'static SeparadorEndereco,
    f: impl FnOnce(&mut Tagger<'static>) -> R,
) -> R {
    TAGGER.with(|celula| {
        let mut celula = celula.borrow_mut();
        let tagger = celula.get_or_insert_with(|| separador.novo_tagger());
        f(tagger)
    })
}

/// Segmenta uma string de endereço em suas partes constituintes utilizando o
/// modelo padrão.
///
/// Devolve o motivo da falha quando o modelo não está disponível.
///
/// ```
/// use enderecobr_rs::separador_endereco::{
///     modelo::obter_caminho_modelo,
///     segmentar_endereco, EnderecoSegmentado, OpcoesSegmentacao, SegmentoEndereco, TipoSegmento,
/// };
///
/// // O exemplo só roda quando o modelo já está no cache: nada de rede aqui.
/// let modelo_existe = obter_caminho_modelo(None).map(|x| x.is_file()).unwrap_or(false);
/// if !modelo_existe {
///     return;
/// }
///
/// // Exemplo de fato:
/// let endereco_segmentado =
///     segmentar_endereco("av n sra copacabana, 123, apt 301",
///                      &OpcoesSegmentacao::sem_probabilidades())
///         .unwrap();
/// let endereco_esperado = EnderecoSegmentado::novo(vec![
///     SegmentoEndereco::novo("av n sra copacabana", TipoSegmento::Logradouro),
///     SegmentoEndereco::novo("123", TipoSegmento::Numero),
///     SegmentoEndereco::novo("apt 301", TipoSegmento::Complemento),
/// ]);
/// assert_eq!(endereco_segmentado, endereco_esperado);
/// ```
pub fn segmentar_endereco(
    texto: &str,
    opcoes: &OpcoesSegmentacao,
) -> Result<EnderecoSegmentado, String> {
    let separador = separador_padrao()?;
    Ok(com_tagger(separador, |tagger| {
        separador.processar(tagger, texto, opcoes)
    }))
}

/// Segmenta vários endereços de uma vez, com o modelo padrão carregado uma única
/// vez. Vide [`segmentar_endereco`] para mais informações. Mais eficiente para
/// processar uma lista ou coluna de endereços.
///
/// A saída mantém a ordem da entrada.
pub fn segmentar_enderecos(
    textos: &[&str],
    opcoes: &OpcoesSegmentacao,
) -> Result<Vec<EnderecoSegmentado>, String> {
    let separador = separador_padrao()?;
    Ok(com_tagger(separador, |tagger| {
        textos
            .iter()
            .map(|texto| separador.processar(tagger, texto, opcoes))
            .collect()
    }))
}

impl EnderecoSegmentado {
    /// Cria a segmentação ainda sem probabilidades calculadas.
    pub fn novo(segmentos: Vec<SegmentoEndereco>) -> EnderecoSegmentado {
        EnderecoSegmentado {
            segmentos,
            probabilidade: None,
            confianca: None,
        }
    }

    /// Serializa os segmentos em JSON. Equivalente a [`segmento_como_json`].
    pub fn como_json(&self) -> String {
        segmento_como_json(self)
    }

    /// Junta os segmentos em um [`Endereco`], padronizando os campos quando
    /// `padronizar` for verdadeiro. Vide [`estruturar_segmentos`].
    pub fn como_endereco(&self, padronizar: bool) -> Endereco {
        estruturar_segmentos(self, padronizar)
    }
}

/// Junta os segmentos em um [`Endereco`] e devolve os campos já separados.
///
/// `padronizar` indica se os campos resultantes devem passar pelas funções de
/// padronização.
///
/// Vide a documentação de [`segmentar_endereco`] e [`estruturar_segmentos`]
/// para mais detalhes.
///
/// ```
/// use enderecobr_rs::separador_endereco::{
///     modelo::obter_caminho_modelo,
///     estruturar_endereco, OpcoesEndereco
/// };
/// use enderecobr_rs::endereco::Endereco;
///
/// // O exemplo só roda quando o modelo já está no cache: nada de rede aqui.
/// let modelo_existe = obter_caminho_modelo(None).map(|x| x.is_file()).unwrap_or(false);
/// if !modelo_existe {
///     return;
/// }
///
/// // Exemplo de fato
/// let endereco =
///     estruturar_endereco("av atlantica, 123, apto 301", &OpcoesEndereco::default())
///         .unwrap();
/// assert_eq!(endereco, Endereco {
///   logradouro: Some("AVENIDA ATLANTICA".to_string()),
///   numero: Some("123".to_string()),
///   complemento: Some("APARTAMENTO 301".to_string()),
///   ..Default::default()
/// });
/// ```
pub fn estruturar_endereco(endereco: &str, opcoes: &OpcoesEndereco) -> Result<Endereco, String> {
    let segmentacao = OpcoesSegmentacao {
        probabilidades: opcoes.probabilidades,
    };
    segmentar_endereco(endereco, &segmentacao)
        .map(|segmentado| estruturar_segmentos(&segmentado, opcoes.padronizar))
}

/// Serializa os segmentos encontrados em JSON. Usando internamente no CLI.
///
/// O campo `tipo` sai como o rótulo do modelo em minúsculas.
///
/// ```
/// use enderecobr_rs::separador_endereco::{EnderecoSegmentado, SegmentoEndereco, TipoSegmento,
/// segmento_como_json};
///
/// let segmentado = EnderecoSegmentado::novo(vec![SegmentoEndereco::novo(
///     "20000-000",
///     TipoSegmento::Cep,
/// )]);
///
/// assert_eq!(
///     segmento_como_json(&segmentado),
///     r#"{"segmentos":[{"valor":"20000-000","tipo":"cep"}]}"#
/// );
/// ```
pub fn segmento_como_json(segmentado: &EnderecoSegmentado) -> String {
    serde_json::to_string(segmentado).unwrap_or_else(|_| "[]".to_string())
}

#[cfg(test)]
mod tests_tipo_segmento {
    use super::TipoSegmento;

    #[test]
    fn converte_rotulo_do_modelo_em_variante() {
        assert_eq!(TipoSegmento::from("LOGRADOURO"), TipoSegmento::Logradouro);
        assert_eq!(
            TipoSegmento::from("ponto_referencia"),
            TipoSegmento::PontoReferencia
        );
        // Rótulo desconhecido não derruba a segmentação.
        assert_eq!(TipoSegmento::from("NOVO_ROTULO"), TipoSegmento::Outro);
    }

    #[test]
    fn como_str_volta_para_o_rotulo() {
        let volta: Vec<TipoSegmento> = TipoSegmento::TODOS
            .iter()
            .map(|tipo| TipoSegmento::from(tipo.como_str()))
            .collect();
        assert_eq!(volta, TipoSegmento::TODOS.to_vec());
    }

    #[test]
    fn serde_usa_o_mesmo_rotulo_de_como_str() {
        let json: Vec<String> = TipoSegmento::TODOS
            .iter()
            .map(|tipo| {
                serde_json::to_value(tipo)
                    .unwrap()
                    .as_str()
                    .unwrap()
                    .to_string()
            })
            .collect();
        let rotulos: Vec<String> = TipoSegmento::TODOS
            .iter()
            .map(|tipo| tipo.como_str().to_string())
            .collect();
        assert_eq!(json, rotulos);
    }

    #[test]
    fn display_escreve_o_rotulo() {
        assert_eq!(TipoSegmento::Cep.to_string(), "cep");
        assert_eq!(TipoSegmento::Denominacao.to_string(), "denominacao");
        assert_eq!(format!("{}", TipoSegmento::Uf), "uf");
    }

    #[test]
    fn todos_cabe_no_enum() {
        // Se a lista `TODOS` repetir uma variante, a contagem denuncia.
        let mut vistos: Vec<&str> = TipoSegmento::TODOS.iter().map(|t| t.como_str()).collect();
        vistos.sort_unstable();
        vistos.dedup();
        assert_eq!(vistos.len(), TipoSegmento::TODOS.len());
    }
}

// Os testes que precisam do modelo e de itens privados ficam aqui; os de
// integração, que só usam a API pública, estão em `tests/crf.rs`.
#[cfg(test)]
mod tests {
    use super::*;
    use crate::endereco::Endereco;
    use crate::separador_endereco::modelo::obter_modelo_no_cache;

    /// Constrói um segmento sem repetir a struct em cada teste.
    fn criar_segmento(valor: &str, tipo: TipoSegmento) -> SegmentoEndereco {
        SegmentoEndereco::novo(valor, tipo)
    }

    /// Constrói uma segmentação a partir dos segmentos, na ordem em que aparecem.
    fn criar_segmentado(segmentos: Vec<SegmentoEndereco>) -> EnderecoSegmentado {
        EnderecoSegmentado::novo(segmentos)
    }

    #[test]
    fn carregar_devolve_erro_com_caminho_inexistente() {
        let Err(erro) = SeparadorEndereco::carregar(PathBuf::from("arquivo_inexistente.crf"))
        else {
            panic!("carregar deveria falhar com caminho inexistente");
        };
        assert!(erro.contains("arquivo_inexistente.crf"));
    }

    #[test]
    fn carregar_devolve_erro_com_arquivo_invalido() {
        // O `Cargo.toml` existe, mas não é um modelo.
        assert!(SeparadorEndereco::carregar(PathBuf::from("Cargo.toml")).is_err());
    }

    #[test]
    fn como_json_serializa_os_segmentos() {
        let segmentado = criar_segmentado(vec![criar_segmento("123", TipoSegmento::Numero)]);

        assert_eq!(
            segmentado.como_json(),
            r#"{"segmentos":[{"valor":"123","tipo":"numero"}]}"#
        );
        assert_eq!(segmento_como_json(&segmentado), segmentado.como_json());
        assert_eq!(
            EnderecoSegmentado::default().como_json(),
            r#"{"segmentos":[]}"#
        );
    }

    #[test]
    fn segmento_como_endereco_sem_padronizar_mantem_os_valores() {
        let segmentado = criar_segmentado(vec![
            criar_segmento("av atlantica", TipoSegmento::Logradouro),
            criar_segmento("123", TipoSegmento::Numero),
            criar_segmento("apto 301", TipoSegmento::Complemento),
        ]);

        assert_eq!(
            segmentado.como_endereco(false),
            Endereco {
                logradouro: Some("av atlantica".to_string()),
                numero: Some("123".to_string()),
                complemento: Some("apto 301".to_string()),
                ..Default::default()
            }
        );
    }

    // Os testes a seguir precisam do modelo. Ele nunca é baixado: quando não
    // está no cache, como no CI, os testes simplesmente passam sem executar.

    #[test]
    fn montar_segmentos_segue_os_rotulos_bio() {
        let Some(caminho) = obter_modelo_no_cache() else {
            return;
        };
        let separador = SeparadorEndereco::carregar(caminho).unwrap();

        // `I-` de tipo diferente do segmento corrente é descartado, e token
        // grudado (sem espaço antes) é colado sem espaço.
        let (tokens, offsets) = separador.extrator.tokenize("a,b 100");
        let tags: Vec<String> = ["B_logradouro", "O", "I_logradouro", "I_numero"]
            .iter()
            .map(|tag| tag.to_string())
            .collect();

        let (segmentos, faixas) = separador.montar_segmentos("a,b 100", &tokens, &tags, &offsets);
        assert_eq!(
            segmentos,
            vec![criar_segmento("ab", TipoSegmento::Logradouro)]
        );
        assert_eq!(faixas, vec![0..3]);

        // `I-` sem segmento anterior é descartado.
        assert_eq!(
            separador
                .montar_segmentos("z", &["z"], &["I_logradouro".to_string()], &[0])
                .0,
            Vec::new()
        );

        // `I-` após espaço junta com espaço.
        assert_eq!(
            separador
                .montar_segmentos(
                    "x 1",
                    &["x", "1"],
                    &["B_numero".to_string(), "I_numero".to_string()],
                    &[0, 2],
                )
                .0,
            vec![criar_segmento("x 1", TipoSegmento::Numero)]
        );

        // Prefixo BIO desconhecido é descartado.
        assert_eq!(
            separador
                .montar_segmentos(
                    "a b",
                    &["a", "b"],
                    &["B_logradouro".to_string(), "X_logradouro".to_string()],
                    &[0, 2],
                )
                .0,
            vec![criar_segmento("a", TipoSegmento::Logradouro)]
        );
    }
}
