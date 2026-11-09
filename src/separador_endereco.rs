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
//!A obtenção do arquivo do modelo (busca, download e cache) fica em [`modelo`].
mod estruturacao;
pub mod features;
pub mod modelo;
pub mod vocabulario;

use std::{cell::RefCell, path::PathBuf, sync::LazyLock};

use crfsuite::{Attribute, Model, Tagger};

use serde::Serialize;

pub use crate::separador_endereco::estruturacao::estruturar_segmentos;
pub use crate::separador_endereco::modelo::{obter_caminho_modelo, obter_modelo};

use crate::{endereco::Endereco, separador_endereco::features::ExtratorFeature};

/// Separador de endereços: divide um texto livre em partes (logradouro,
/// número, complemento, CEP etc.) com o auxílio de um modelo probabilístico.
///
/// Em geral não é preciso criar uma instância: [`segmentar_endereco`] e
/// [`estruturar_endereco`] já usam o modelo distribuído com o pacote.
/// Instancie apenas quando quiser trabalhar com um arquivo de modelo próprio.
pub struct SeparadorEndereco {
    /// Modelo usado na classificação dos trechos do endereço.
    pub model: Model,
    /// Responsável por transformar o texto nos atributos lidos pelo modelo.
    pub extrator: ExtratorFeature,
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
#[derive(Serialize, Debug, PartialEq, Eq, Clone, Copy, Hash)]
#[serde(rename_all = "snake_case")]
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
    pub const TODOS: [TipoSegmento; 18] = [
        TipoSegmento::Logradouro,
        TipoSegmento::Numero,
        TipoSegmento::Complemento,
        TipoSegmento::Empreendimento,
        TipoSegmento::Parcela,
        TipoSegmento::QuilometragemVia,
        TipoSegmento::Referencia,
        TipoSegmento::PontoReferencia,
        TipoSegmento::Denominacao,
        TipoSegmento::Localidade,
        TipoSegmento::NucleoRural,
        TipoSegmento::RecursoNatural,
        TipoSegmento::Cep,
        TipoSegmento::Municipio,
        TipoSegmento::Uf,
        TipoSegmento::Cadastro,
        TipoSegmento::Ruido,
        TipoSegmento::Outro,
    ];

    /// Rótulo em minúsculas, igual ao usado na serialização e nos dumps do modelo.
    ///
    /// ```
    /// use enderecobr_rs::separador_endereco::TipoSegmento;
    ///
    /// assert_eq!(TipoSegmento::Cep.como_str(), "cep");
    /// ```
    pub const fn como_str(self) -> &'static str {
        match self {
            TipoSegmento::Logradouro => "logradouro",
            TipoSegmento::Numero => "numero",
            TipoSegmento::Complemento => "complemento",
            TipoSegmento::Empreendimento => "empreendimento",
            TipoSegmento::Parcela => "parcela",
            TipoSegmento::QuilometragemVia => "quilometragem_via",
            TipoSegmento::Referencia => "referencia",
            TipoSegmento::PontoReferencia => "ponto_referencia",
            TipoSegmento::Denominacao => "denominacao",
            TipoSegmento::Localidade => "localidade",
            TipoSegmento::NucleoRural => "nucleo_rural",
            TipoSegmento::RecursoNatural => "recurso_natural",
            TipoSegmento::Cep => "cep",
            TipoSegmento::Municipio => "municipio",
            TipoSegmento::Uf => "uf",
            TipoSegmento::Cadastro => "cadastro",
            TipoSegmento::Ruido => "ruido",
            TipoSegmento::Outro => "outros",
        }
    }
}

impl std::fmt::Display for TipoSegmento {
    /// Escreve o mesmo texto de [`TipoSegmento::como_str`].
    ///
    /// ```
    /// use enderecobr_rs::separador_endereco::TipoSegmento;
    ///
    /// assert_eq!(TipoSegmento::Referencia.to_string(), "referencia");
    /// ```
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(self.como_str())
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
            .into_iter()
            .find(|tipo| tipo.como_str().eq_ignore_ascii_case(rotulo))
            .unwrap_or(TipoSegmento::Outro)
    }
}

/// Um trecho do endereço junto com o tipo de informação que ele representa.
#[derive(Serialize, Debug, PartialEq, Clone)]
pub struct SegmentoEndereco {
    pub valor: String,
    pub tipo: TipoSegmento,
}

/// Resultado da segmentação: os trechos identificados, na ordem em que aparecem
/// no texto original.
///
/// ```
/// use enderecobr_rs::separador_endereco::{
///     segmento_como_json, EnderecoSegmentado, SegmentoEndereco, TipoSegmento,
/// };
///
/// let segmentado = EnderecoSegmentado {
///     segmentos: vec![
///         SegmentoEndereco {
///             valor: "av atlantica".to_string(),
///             tipo: TipoSegmento::Logradouro,
///         },
///         SegmentoEndereco {
///             valor: "123".to_string(),
///             tipo: TipoSegmento::Numero,
///         },
///     ],
/// };
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
}

impl SeparadorEndereco {
    /// Cria um separador a partir de um arquivo de modelo já treinado.
    ///
    /// Devolve erro quando o arquivo não existe, não é um modelo válido ou não
    /// consegue ser usado para classificar. Depois de criado, o separador não
    /// falha mais ao segmentar: a única falha restante seria falta de memória,
    /// que já é testada aqui.
    pub fn carregar(caminho: PathBuf) -> Result<SeparadorEndereco, String> {
        let model = Model::from_file(&caminho.to_string_lossy()).map_err(|erro| {
            format!(
                "Não foi possível carregar o modelo {}: {erro}",
                caminho.display()
            )
        })?;

        let separador = SeparadorEndereco {
            model,
            extrator: ExtratorFeature::new(None),
        };

        // Cria um tagger de teste e o descarta: garante já na carga que o modelo
        // é utilizável, para a segmentação em si não ter como falhar.
        drop(separador.novo_tagger());

        Ok(separador)
    }

    /// Converte uma lista de tokens nos atributos que o modelo usa para
    /// classificar cada um. Raramente necessária fora do uso interno.
    pub fn tokens2attributes(&self, tokens: &[&str]) -> Vec<Vec<Attribute>> {
        self.extrator.tokens2attributes(tokens)
    }

    /// Junta os tokens em segmentos, seguindo os rótulos BIO devolvidos pelo modelo.
    fn montar_segmentos(
        &self,
        original: &str,
        tokens: &[&str],
        tags: &[String],
        offsets: &[usize],
    ) -> Vec<SegmentoEndereco> {
        let mut segmentos = Vec::with_capacity(4);
        for ((tok, tok_tipo), offset) in tokens.iter().zip(tags).zip(offsets) {
            // Rótulos são "B_<TIPO>", "I_<TIPO>" ou "O": comparar o byte do BIO
            // evita comparações de string no hot path.
            let Some((bio, tipo)) = tok_tipo.split_once('_') else {
                continue; // "O"
            };

            let tipo = TipoSegmento::from(tipo);
            match bio.as_bytes().first().copied() {
                Some(b'B') => segmentos.push(SegmentoEndereco {
                    valor: tok.to_string(),
                    tipo,
                }),
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
                }
                _ => continue,
            }
        }

        segmentos
    }

    /// Segmenta um endereço com este separador. Vide [`segmentar_endereco`].
    pub fn segmentar(&self, texto: &str) -> EnderecoSegmentado {
        let mut tagger = self.novo_tagger();
        self.processar_com_tagger(&mut tagger, texto)
    }

    /// Segmenta vários endereços com este separador, reaproveitando o mesmo
    /// tagger entre eles (mais rápido que chamar [`segmentar`](Self::segmentar)
    /// em sequência).
    ///
    /// A saída mantém a ordem da entrada.
    pub fn segmentar_enderecos(&self, textos: &[&str]) -> Vec<EnderecoSegmentado> {
        let mut tagger = self.novo_tagger();
        textos
            .iter()
            .map(|texto| self.processar_com_tagger(&mut tagger, texto))
            .collect()
    }

    /// Cria um tagger para este modelo.
    ///
    /// A criação já foi testada em [`carregar`](Self::carregar), então a única
    /// falha possível aqui seria falta de memória.
    fn novo_tagger(&self) -> Tagger<'_> {
        self.model
            .tagger()
            .expect("Não foi possível criar o tagger do CRF (memória insuficiente)")
    }

    /// Pipeline completo (tokenização, features, modelo e remontagem dos segmentos),
    /// usando um tagger já pronto para ele poder ser reaproveitado.
    fn processar_com_tagger(&self, tagger: &mut Tagger<'_>, texto: &str) -> EnderecoSegmentado {
        let (tokens, offsets) = self.extrator.tokenize(texto);
        let atributos = self.tokens2attributes(&tokens);
        let tags = tagger
            .tag(&atributos)
            .expect("Não foi possível executar o tagging do CRF");

        EnderecoSegmentado {
            segmentos: self.montar_segmentos(texto, &tokens, &tags, &offsets),
        }
    }
}

// Em Rust, a constant é criada durante a compilação, então só posso chamar funções muito restritas
// quando uso `const`. Nesse caso,  como tenho uma construção complexa da struct `Padronizador`,
// tenho que usar static com inicialização Lazy (o LazyLock aqui previne condições de corrida).
// O `Result` guarda a falha (modelo indisponível) para que ela vire um erro comum em
// vez de um panic na primeira chamada.
static SEPARADOR: LazyLock<Result<SeparadorEndereco, String>> =
    LazyLock::new(|| SeparadorEndereco::carregar(obter_modelo(None)?));

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
/// # Panics
///
/// Panic se o modelo padrão não puder ser obtido ou carregado. Use
/// [`tentar_segmentar_endereco`] para tratar esse caso como erro.
///
/// ```
/// use enderecobr_rs::separador_endereco::{
///     modelo::{obter_modelo, VAR_AMBIENTE_SEM_DOWNLOAD},
///     segmentar_endereco, EnderecoSegmentado, SegmentoEndereco, TipoSegmento,
/// };
///
/// // Evitando problemas no CI
/// std::env::set_var(VAR_AMBIENTE_SEM_DOWNLOAD, "true");
/// let modelo_existe = obter_modelo(None).map(|x| x.exists()).unwrap_or(false);
/// if !modelo_existe {
///     return;
/// }
///
/// // Exemplo de fato:
/// let endereco_segmentado = segmentar_endereco("av n sra copacabana, 123, apt 301");
/// let endereco_esperado = EnderecoSegmentado {
///     segmentos: vec![
///         SegmentoEndereco {
///             valor: "av n sra copacabana".to_string(),
///             tipo: TipoSegmento::Logradouro,
///         },
///         SegmentoEndereco {
///             valor: "123".to_string(),
///             tipo: TipoSegmento::Numero,
///         },
///         SegmentoEndereco {
///             valor: "apt 301".to_string(),
///             tipo: TipoSegmento::Complemento,
///         },
///     ],
/// };
/// assert_eq!(endereco_segmentado, endereco_esperado);
/// ```
pub fn segmentar_endereco(texto: &str) -> EnderecoSegmentado {
    tentar_segmentar_endereco(texto).expect("Não foi possível segmentar o endereço")
}

/// Igual a [`segmentar_endereco`], mas devolve o motivo da falha em vez de
/// entrar em panic quando o modelo não está disponível.
pub fn tentar_segmentar_endereco(texto: &str) -> Result<EnderecoSegmentado, String> {
    let separador = separador_padrao()?;
    Ok(com_tagger(separador, |tagger| {
        separador.processar_com_tagger(tagger, texto)
    }))
}

/// Segmenta vários endereços de uma vez, com o modelo padrão carregado uma única
/// vez. Vide [`segmentar_endereco`] para mais informações. Mais eficiente de processar
/// uma lista ou coluna de endereços.
///
/// # Panics
///
/// Panic se o modelo padrão não puder ser obtido ou carregado. Use
/// [`tentar_segmentar_enderecos`] para tratar esse caso como erro.
pub fn segmentar_enderecos(textos: &[&str]) -> Vec<EnderecoSegmentado> {
    tentar_segmentar_enderecos(textos).expect("Não foi possível segmentar os endereços")
}

/// Igual a [`segmentar_enderecos`], mas devolve o motivo da falha em vez de
/// entrar em panic quando o modelo não está disponível.
pub fn tentar_segmentar_enderecos(textos: &[&str]) -> Result<Vec<EnderecoSegmentado>, String> {
    let separador = separador_padrao()?;
    Ok(com_tagger(separador, |tagger| {
        textos
            .iter()
            .map(|texto| separador.processar_com_tagger(tagger, texto))
            .collect()
    }))
}

impl EnderecoSegmentado {
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
/// # Panics
///
/// Panic se o modelo padrão não puder ser carregado. Use
/// [`tentar_estruturar_endereco`] para tratar esse caso como erro.
///
/// ```
/// use enderecobr_rs::separador_endereco::{
///     modelo::{obter_modelo, VAR_AMBIENTE_SEM_DOWNLOAD},
///     estruturar_endereco
/// };
/// use enderecobr_rs::endereco::Endereco;
///
/// // Evitando problemas no CI
/// std::env::set_var(VAR_AMBIENTE_SEM_DOWNLOAD, "true");
/// let modelo_existe = obter_modelo(None).map(|x| x.exists()).unwrap_or(false);
/// if !modelo_existe {
///     return;
/// }
///
/// // Exemplo de fato
/// let endereco = estruturar_endereco("av atlantica, 123, apto 301", true);
/// assert_eq!(endereco, Endereco {
///   logradouro: Some("AVENIDA ATLANTICA".to_string()),
///   numero: Some("123".to_string()),
///   complemento: Some("APARTAMENTO 301".to_string()),
///   ..Default::default()
/// });
/// ```
pub fn estruturar_endereco(endereco: &str, padronizar: bool) -> Endereco {
    tentar_estruturar_endereco(endereco, padronizar)
        .expect("Não foi possível estruturar o endereço")
}

/// Igual a [`estruturar_endereco`], mas devolve o motivo da falha em vez de
/// entrar em panic quando o modelo não está disponível.
pub fn tentar_estruturar_endereco(endereco: &str, padronizar: bool) -> Result<Endereco, String> {
    tentar_segmentar_endereco(endereco)
        .map(|segmentado| estruturar_segmentos(&segmentado, padronizar))
}

/// Serializa os segmentos encontrados em JSON. Usando internamente no CLI.
///
/// O campo `tipo` sai como o rótulo do modelo em minúsculas.
///
/// ```
/// use enderecobr_rs::separador_endereco::{EnderecoSegmentado, SegmentoEndereco, TipoSegmento,
/// segmento_como_json};
///
/// let segmentado = EnderecoSegmentado {
///     segmentos: vec![SegmentoEndereco {
///         valor: "20000-000".to_string(),
///         tipo: TipoSegmento::Cep,
///     }],
/// };
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
mod testes_tipo_segmento {
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
        for tipo in TipoSegmento::TODOS {
            assert_eq!(TipoSegmento::from(tipo.como_str()), tipo);
        }
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

#[cfg(test)]
mod tests {
    use super::*;
    use crate::endereco::Endereco;
    use crate::separador_endereco::modelo::{
        NOME_ARQUIVO_MODELO, NOME_DIRETORIO_CACHE, VAR_AMBIENTE_MODELO, VAR_AMBIENTE_SEM_DOWNLOAD,
        VERSAO_MODELO,
    };

    /// Constrói um segmento sem repetir a struct em cada teste.
    fn criar_segmento(valor: &str, tipo: TipoSegmento) -> SegmentoEndereco {
        SegmentoEndereco {
            valor: valor.to_string(),
            tipo,
        }
    }

    /// Constrói uma segmentação a partir dos segmentos, na ordem em que aparecem.
    fn criar_segmentado(segmentos: Vec<SegmentoEndereco>) -> EnderecoSegmentado {
        EnderecoSegmentado { segmentos }
    }

    /// Caminho do modelo padrão no cache do sistema, sem passar pelas
    /// variáveis de ambiente (portanto nunca baixa nada).
    fn obter_modelo_no_cache() -> Option<PathBuf> {
        dirs::cache_dir()
            .map(|cache| {
                cache
                    .join(NOME_DIRETORIO_CACHE)
                    .join(VERSAO_MODELO)
                    .join(NOME_ARQUIVO_MODELO)
            })
            .filter(|caminho| caminho.is_file())
    }

    /// Prepara o ambiente para os testes que usam o modelo padrão:
    /// devolve o caminho do modelo ou `None` (teste pulado) quando ele não
    /// está disponível, como no CI, que não baixa o modelo.
    ///
    /// As variáveis de ambiente também são apontadas para esse modelo, para
    /// evitar downloads acidentais e interferência dos testes de `modelo.rs`,
    /// que manipulam as mesmas variáveis.
    fn preparar_modelo_padrao() -> Option<PathBuf> {
        let caminho = obter_modelo_no_cache()?;
        std::env::set_var(VAR_AMBIENTE_MODELO, caminho.as_os_str());
        std::env::set_var(VAR_AMBIENTE_SEM_DOWNLOAD, "true");
        Some(caminho)
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
    fn carregar_permite_segmentar_com_o_modelo_do_cache() {
        let Some(caminho) = obter_modelo_no_cache() else {
            return;
        };
        let separador = SeparadorEndereco::carregar(caminho).unwrap();

        let atributos = separador.tokens2attributes(&["rua", "brasil", "123"]);
        assert_eq!(atributos.len(), 3);
        for atributos_token in &atributos {
            assert!(!atributos_token.is_empty());
        }

        assert_eq!(
            separador.segmentar("rua brasil, 123"),
            criar_segmentado(vec![
                criar_segmento("rua brasil", TipoSegmento::Logradouro),
                criar_segmento("123", TipoSegmento::Numero),
            ])
        );

        assert_eq!(
            separador.segmentar_enderecos(&["rua brasil, 123", "r brasil, 50"]),
            vec![
                criar_segmentado(vec![
                    criar_segmento("rua brasil", TipoSegmento::Logradouro),
                    criar_segmento("123", TipoSegmento::Numero),
                ]),
                criar_segmentado(vec![
                    criar_segmento("r brasil", TipoSegmento::Logradouro),
                    criar_segmento("50", TipoSegmento::Numero),
                ]),
            ]
        );
    }

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

        assert_eq!(
            separador.montar_segmentos("a,b 100", &tokens, &tags, &offsets),
            vec![criar_segmento("ab", TipoSegmento::Logradouro)]
        );

        // `I-` sem segmento anterior é descartado.
        assert_eq!(
            separador.montar_segmentos("z", &["z"], &["I_logradouro".to_string()], &[0],),
            Vec::new()
        );

        // `I-` após espaço junta com espaço.
        assert_eq!(
            separador.montar_segmentos(
                "x 1",
                &["x", "1"],
                &["B_numero".to_string(), "I_numero".to_string()],
                &[0, 2],
            ),
            vec![criar_segmento("x 1", TipoSegmento::Numero)]
        );

        // Prefixo BIO desconhecido é descartado.
        assert_eq!(
            separador.montar_segmentos(
                "a b",
                &["a", "b"],
                &["B_logradouro".to_string(), "X_logradouro".to_string()],
                &[0, 2],
            ),
            vec![criar_segmento("a", TipoSegmento::Logradouro)]
        );
    }

    #[test]
    fn segmentar_endereco_separa_partes_simples() {
        if preparar_modelo_padrao().is_none() {
            return;
        }

        assert_eq!(
            segmentar_endereco("rua brasil, 123"),
            criar_segmentado(vec![
                criar_segmento("rua brasil", TipoSegmento::Logradouro),
                criar_segmento("123", TipoSegmento::Numero),
            ])
        );
    }

    #[test]
    fn tentar_segmentar_endereco_devolve_ok() {
        if preparar_modelo_padrao().is_none() {
            return;
        }

        assert_eq!(
            tentar_segmentar_endereco("r brasil, 50"),
            Ok(criar_segmentado(vec![
                criar_segmento("r brasil", TipoSegmento::Logradouro),
                criar_segmento("50", TipoSegmento::Numero),
            ]))
        );
    }

    #[test]
    fn segmentar_enderecos_mantem_a_ordem_da_entrada() {
        if preparar_modelo_padrao().is_none() {
            return;
        }

        let entradas = ["rua brasil, 123", "av atlantica, 123, apto 301"];
        let saida_esperada = vec![
            criar_segmentado(vec![
                criar_segmento("rua brasil", TipoSegmento::Logradouro),
                criar_segmento("123", TipoSegmento::Numero),
            ]),
            criar_segmentado(vec![
                criar_segmento("av atlantica", TipoSegmento::Logradouro),
                criar_segmento("123", TipoSegmento::Numero),
                criar_segmento("apto 301", TipoSegmento::Complemento),
            ]),
        ];

        assert_eq!(segmentar_enderecos(&entradas), saida_esperada);
        assert_eq!(tentar_segmentar_enderecos(&entradas), Ok(saida_esperada));
    }

    #[test]
    fn estruturar_endereco_padroniza_os_campos() {
        if preparar_modelo_padrao().is_none() {
            return;
        }

        assert_eq!(
            estruturar_endereco("av atlantica, 123, apto 301", true),
            Endereco {
                logradouro: Some("AVENIDA ATLANTICA".to_string()),
                numero: Some("123".to_string()),
                complemento: Some("APARTAMENTO 301".to_string()),
                ..Default::default()
            }
        );
    }

    #[test]
    fn estruturar_endereco_sem_padronizar_mantem_os_segmentos() {
        if preparar_modelo_padrao().is_none() {
            return;
        }

        assert_eq!(
            estruturar_endereco("av atlantica, 123, apto 301", false),
            Endereco {
                logradouro: Some("av atlantica".to_string()),
                numero: Some("123".to_string()),
                complemento: Some("apto 301".to_string()),
                ..Default::default()
            }
        );
    }

    #[test]
    fn estruturar_endereco_preenche_localidade_e_cep() {
        if preparar_modelo_padrao().is_none() {
            return;
        }

        assert_eq!(
            estruturar_endereco(
                "r a, 1, ap 2, copacabana, rio de janeiro, rj, 22000-000",
                true,
            ),
            Endereco {
                logradouro: Some("RUA A".to_string()),
                numero: Some("1".to_string()),
                complemento: Some("APARTAMENTO 2".to_string()),
                localidade: Some("COPACABANA".to_string()),
                cep: Some("22000-000".to_string()),
            }
        );

        assert_eq!(
            tentar_estruturar_endereco("r a, 1, ap 2", false),
            Ok(Endereco {
                logradouro: Some("r a".to_string()),
                numero: Some("1".to_string()),
                complemento: Some("ap 2".to_string()),
                ..Default::default()
            })
        );
    }
}
