from collections.abc import Iterable
from pathlib import Path

def normalizar(valor: str) -> str:
    """
    Normaliza uma string para processamento posterior, removendo diacríticos e
    caracteres especiais, convertendo para maiúsculas e reduzindo espaços.

    Parameters
    ----------
    valor : str
        Texto bruto a ser normalizado.

    Returns
    -------
    str
        Texto normalizado: maiúsculas, sem acentos, com espaços das pontas
        removidos e espaços internos reduzidos a um único espaço.

    Examples
    --------
    >>> import enderecobr
    >>> enderecobr.normalizar('Olá, mundo')
    'OLA, MUNDO'
    >>> enderecobr.normalizar('R. DO AÇAÍ 15º')
    'R. DO ACAI 15O'

    """

def padronizar_logradouros(valor: str) -> str:
    """
    Padroniza uma string representando logradouros de municípios brasileiros.

    Realiza uma série de transformações para normalizar nomes de ruas, avenidas e
    outros tipos de logradouros segundo convenções comuns em bases de endereços no Brasil.

    Parameters
    ----------
    valor : str
        Texto bruto representando um logradouro (ex: 'r. gen.. glicério').

    Returns
    -------
    str
        Texto padronizado em caixa alta, sem acentos, com abreviações expandidas
        e formatação consistente.

    Examples
    --------
    >>> import enderecobr
    >>> enderecobr.padronizar_logradouros("r. gen.. glicério")
    'RUA GENERAL GLICERIO'

    Notes
    -----
    As seguintes operações são aplicadas sequencialmente:

    - Remoção de espaços extras no início, fim e entre palavras;
    - Conversão para maiúsculas;
    - Remoção de acentos e conversão de caracteres não-ASCII;
    - Normalização de pontos em abreviações (ex: 'gen..' → 'GEN');
    - Inserção de espaços após abreviações com pontos (ex: 'R.JOSE' → 'R. JOSE');
    - Expansão de abreviações comuns (ex: 'R.' → 'RUA', 'AV.' → 'AVENIDA');
    - Correção de erros ortográficos frequentes (ex: 'GLICERIO' em vez de 'GLICÉRIO').

    As expressões regulares são compiladas na primeira chamada, portanto a primeira
    execução pode ser mais lenta. Chamadas subsequentes reutilizam as regexes compiladas.
    """

def padronizar_numeros(valor: str) -> str:
    """
    Padroniza uma string representando números de logradouros.

    Normaliza números de endereços, removendo formatações inconsistentes e
    tratando casos especiais como ausência de número (ex: "SN", "S/N", etc).

    Parameters
    ----------
    valor : str
        Texto bruto representando o número de um logradouro (ex: '0210', 'S. N. ').

    Returns
    -------
    str
        Número padronizado. Números comuns têm zeros à esquerda removidos;
        valores nulos ou variações de "SN" são convertidos para "S/N".

    Examples
    --------
    >>> import enderecobr
    >>> enderecobr.padronizar_numeros("0210")
    '210'
    >>> enderecobr.padronizar_numeros("  S. N.  ")
    'S/N'

    Notes
    -----
    As seguintes operações são aplicadas:

    - Remoção de espaços extras no início, fim e entre caracteres;
    - Remoção de zeros à esquerda em números;
    - Detecção e substituição de variações de "sem número" (SN, S N, S./N., etc) por "S/N";
    - Retorno de string vazia se a entrada for completamente inválida ou nula.

    As expressões regulares são compiladas na primeira chamada, portanto a primeira
    execução pode ser mais lenta. Chamadas subsequentes reutilizam as regexes compiladas.
    """

def padronizar_numeros_para_int(valor: str) -> int | None:
    """
    Padroniza uma string representando números de logradouros para um inteiro.

    Remove zeros à esquerda; variações de SN (S/N, S N etc.) resultam em None.
    Apenas números simples (sem espaços) são convertidos.

    Parameters
    ----------
    valor : str
        Texto bruto representando o número de um logradouro.

    Returns
    -------
    int or None
        Número convertido, ou None caso a entrada seja inválida, vazia,
        sem número ou contenha mais de um número.

    Examples
    --------
    >>> import enderecobr
    >>> enderecobr.padronizar_numeros_para_int('0210')
    210
    >>> enderecobr.padronizar_numeros_para_int('001')
    1
    >>> enderecobr.padronizar_numeros_para_int('1')
    1
    >>> enderecobr.padronizar_numeros_para_int('0') is None
    True
    >>> enderecobr.padronizar_numeros_para_int('') is None
    True
    >>> enderecobr.padronizar_numeros_para_int('S/N') is None
    True
    >>> enderecobr.padronizar_numeros_para_int('0180 0181') is None
    True

    """

def padronizar_numeros_para_string(valor: float) -> str:
    """
    Converte um valor numérico para a representação textual de número de logradouro.

    Valores menores ou iguais a zero são convertidos para S/N; valores decimais
    são truncados.

    Parameters
    ----------
    valor : int or float
        Número a ser convertido.

    Returns
    -------
    str
        Representação textual do número, ou S/N para valores não positivos.

    Examples
    --------
    >>> import enderecobr
    >>> enderecobr.padronizar_numeros_para_string(210)
    '210'
    >>> enderecobr.padronizar_numeros_para_string(1.1)
    '1'
    >>> enderecobr.padronizar_numeros_para_string(0)
    'S/N'
    >>> enderecobr.padronizar_numeros_para_string(-11)
    'S/N'

    """

def padronizar_complementos(valor: str) -> str:
    """
    Padroniza uma string representando complementos de logradouros.

    Parameters
    ----------
    valor : str
        Texto bruto representando um complemento (ex: 'APTO. 405', 'QD1 LT2 CS3').

    Returns
    -------
    str
        Texto padronizado em caixa alta, sem acentos, com abreviações expandidas
        e formatação consistente.

    Examples
    --------
    >>> import enderecobr
    >>> enderecobr.padronizar_complementos("QD1 LT2 CS3")
    'QUADRA 1 LOTE 2 CASA 3'
    >>> enderecobr.padronizar_complementos("APTO. 405")
    'APARTAMENTO 405'

    Notes
    -----
    As seguintes operações são aplicadas:

    - Remoção de espaços extras no início, fim e entre palavras;
    - Conversão para maiúsculas;
    - Remoção de acentos e caracteres não ASCII;
    - Normalização de pontos em abreviações (ex: 'APTO.' → 'APARTAMENTO');
    - Expansão de abreviações comuns (ex: 'QD' → 'QUADRA', 'LT' → 'LOTE', 'CS' → 'CASA');
    - Correção de erros ortográficos ou variações comuns.

    As expressões regulares são compiladas na primeira chamada, portanto a primeira
    execução pode ser mais lenta. Chamadas subsequentes reutilizam as regexes compiladas.
    """

def padronizar_bairros(valor: str) -> str:
    """
    Padroniza uma string representando bairros de municípios brasileiros.

    Examples
    --------
    >>> import enderecobr
    >>> enderecobr.padronizar_bairros("PRQ IND")
    'PARQUE INDUSTRIAL'
    >>> enderecobr.padronizar_bairros("NSA SEN DE FATIMA")
    'NOSSA SENHORA DE FATIMA'
    >>> enderecobr.padronizar_bairros("ILHA DO GOV")
    'ILHA DO GOVERNADOR'

    Notes
    -----
    Operações realizadas durante a padronização:

    - Remoção de espaços em branco antes, depois e excesso entre palavras;
    - Conversão para caixa alta;
    - Remoção de acentos e caracteres não ASCII;
    - Adição de espaços após abreviações com pontos;
    - Expansão de abreviações comuns usando expressões regulares;
    - Correção de pequenos erros ortográficos.

    As expressões regulares são compiladas na primeira chamada, portanto a primeira
    execução pode ser mais lenta. Chamadas subsequentes reutilizam as regexes compiladas.
    """

def padronizar_municipios(valor: str) -> str:
    """
    Padroniza uma string representando municípios brasileiros.

    Parameters
    ----------
    valor : str
        String contendo o nome ou código de um município brasileiro.
        Pode ser nome (com variações de caixa, acentos, espaçamento),
        código IBGE (7 ou 8 dígitos, com ou sem zeros à esquerda), ou string vazia.

    Returns
    -------
    str
        Nome canônico do município em caixa alta, sem acentos, com correções
        ortográficas e atualizações conforme o IBGE 2022. **Valores que não
        casem com nenhum município conhecido** (nem por grafia exata, nem por
        aproximação fonética) **retornam string vazia** — trate `""` como
        "município desconhecido".

    Examples
    --------
    >>> import enderecobr
    >>> enderecobr.padronizar_municipios("3304557")
    'RIO DE JANEIRO'
    >>> enderecobr.padronizar_municipios("003304557")
    'RIO DE JANEIRO'
    >>> enderecobr.padronizar_municipios("  3304557  ")
    'RIO DE JANEIRO'
    >>> enderecobr.padronizar_municipios("RIO DE JANEIRO")
    'RIO DE JANEIRO'
    >>> enderecobr.padronizar_municipios("rio de janeiro")
    'RIO DE JANEIRO'
    >>> enderecobr.padronizar_municipios("SÃO PAULO")
    'SAO PAULO'
    >>> enderecobr.padronizar_municipios("PARATI")
    'PARATY'
    >>> enderecobr.padronizar_municipios("AUGUSTO SEVERO")
    'CAMPO GRANDE'
    >>> enderecobr.padronizar_municipios("SAO VALERIO DA NATIVIDADE")
    'SAO VALERIO'
    >>> enderecobr.padronizar_municipios("LAGOA DANTA")
    "LAGOA D'ANTA"
    >>> enderecobr.padronizar_municipios("")  # entrada vazia
    ''
    >>> enderecobr.padronizar_municipios("BANANA")  # irreconhecível
    ''
    >>> enderecobr.padronizar_municipios("!!!!")  # sem conteúdo útil
    ''
    >>> enderecobr.padronizar_municipios("PARATI!!!!")  # ruído descartado antes da busca
    'PARATY'

    Notes
    -----
    As seguintes operações são realizadas:

    - Remoção de espaços em branco no início/fim e excesso entre palavras.
    - Conversão para caixa alta.
    - Remoção de zeros à esquerda em códigos numéricos.
    - Busca do nome completo do município a partir do código IBGE.
    - Remoção de acentos e caracteres não ASCII.
    - Correção de erros ortográficos comuns e nomes desatualizados,
      com base na lista oficial de municípios do IBGE (2022).

    As expressões regulares são compiladas na primeira chamada, portanto a primeira
    execução pode ser mais lenta. Chamadas subsequentes reutilizam as regexes compiladas.
    """

def is_dado_faltante(valor: str) -> bool:
    """
    Identifica se uma string representa um dado faltante.

    Parameters
    ----------
    valor : str
        Texto a ser verificado.

    Returns
    -------
    bool
        True se o texto corresponder a um padrão de dado faltante
        (ex: SI, NS, NI, NA), False caso contrário.

    Examples
    --------
    >>> import enderecobr
    >>> enderecobr.is_dado_faltante('SI')
    True
    >>> enderecobr.is_dado_faltante('SEM INFORMAÇÃO')
    True
    >>> enderecobr.is_dado_faltante('NA')
    True
    >>> enderecobr.is_dado_faltante('N CONSTA')
    True
    >>> enderecobr.is_dado_faltante('RUA B')
    False

    """

def padronizar_estados_para_nome(valor: str) -> str:
    """
    Padroniza uma string representando estados brasileiros para seu nome por extenso,
    porém sem diacríticos.

    Parameters
    ----------
    valor : str
        String contendo o código numérico (ex: '21', '021'), sigla (ex: 'MA', 'ma') ou nome
        de um estado brasileiro. Pode conter espaços extras ou formatação irregular.

    Returns
    -------
    str
        Nome por extenso do estado em caixa alta e sem diacríticos (ex: 'MARANHAO').
        Retorna string vazia se o valor for inválido, vazio ou não corresponder a um estado.

    Notes
    -----
    Operações realizadas durante a padronização:

    - Remoção de espaços em branco no início e fim, e espaços extras internos;
    - Conversão para caixa alta;
    - Remoção de zeros à esquerda (em códigos numéricos);
    - Mapeamento partir do código numérico ou da abreviação da UF, do nome completo de cada estado.

    Examples
    --------
    >>> import enderecobr
    >>> enderecobr.padronizar_estados_para_nome("21")
    'MARANHAO'
    >>> enderecobr.padronizar_estados_para_nome("021")
    'MARANHAO'
    >>> enderecobr.padronizar_estados_para_nome("MA")
    'MARANHAO'
    >>> enderecobr.padronizar_estados_para_nome(" 21")
    'MARANHAO'
    >>> enderecobr.padronizar_estados_para_nome(" MA ")
    'MARANHAO'
    >>> enderecobr.padronizar_estados_para_nome("ma")
    'MARANHAO'
    >>> enderecobr.padronizar_estados_para_nome("")
    ''
    >>> enderecobr.padronizar_estados_para_nome("me")
    ''
    >>> enderecobr.padronizar_estados_para_nome("maranhao")
    'MARANHAO'

    """

def padronizar_estados_para_codigo(valor: str) -> str:
    """
    Padroniza uma string representando estados brasileiros para o código do IBGE.

    Parameters
    ----------
    valor : str
        Código numérico (ex: 21, 021), sigla (ex: MA, ma) ou nome de
        um estado brasileiro.

    Returns
    -------
    str
        Código do IBGE do estado (ex: 21), em caixa alta. Retorna string vazia
        se o valor for inválido, vazio ou não corresponder a um estado.

    Examples
    --------
    >>> import enderecobr
    >>> enderecobr.padronizar_estados_para_codigo('21')
    '21'
    >>> enderecobr.padronizar_estados_para_codigo('021')
    '21'
    >>> enderecobr.padronizar_estados_para_codigo('MA')
    '21'
    >>> enderecobr.padronizar_estados_para_codigo('')
    ''
    >>> enderecobr.padronizar_estados_para_codigo('me')
    ''
    >>> enderecobr.padronizar_estados_para_codigo('maranhao')
    '21'

    """

def padronizar_estados_para_sigla(valor: str) -> str:
    """
    Padroniza uma string representando estados brasileiros para sua sigla de duas letras.

    Parameters
    ----------
    valor : str
        Código numérico (ex: 21, 021), sigla (ex: MA, ma) ou nome de
        um estado brasileiro.

    Returns
    -------
    str
        Sigla da UF em caixa alta (ex: MA). Retorna string vazia se o valor for
        inválido, vazio ou não corresponder a um estado.

    Examples
    --------
    >>> import enderecobr
    >>> enderecobr.padronizar_estados_para_sigla('21')
    'MA'
    >>> enderecobr.padronizar_estados_para_sigla('021')
    'MA'
    >>> enderecobr.padronizar_estados_para_sigla('MA')
    'MA'
    >>> enderecobr.padronizar_estados_para_sigla('')
    ''
    >>> enderecobr.padronizar_estados_para_sigla('me')
    ''
    >>> enderecobr.padronizar_estados_para_sigla('maranhao')
    'MA'

    """

def padronizar_tipo_logradouro(valor: str) -> str:
    """
    Padroniza uma string representando complementos de logradouros.

    Examples
    --------
    >>> import enderecobr
    >>> enderecobr.padronizar_tipo_logradouro("R")
    'RUA'
    >>> enderecobr.padronizar_tipo_logradouro("AVE")
    'AVENIDA'
    >>> enderecobr.padronizar_tipo_logradouro("QDRA")
    'QUADRA'

    Notes
    -----
    Operações realizadas durante a padronização:

    - Remoção de espaços em branco antes e depois das strings e remoção de espaços em excesso entre palavras.
    - Conversão de caracteres para caixa alta.
    - Remoção de acentos e caracteres não ASCII.
    - Adição de espaços após abreviações sinalizadas por pontos.
    - Expansão de abreviações frequentemente utilizadas através de expressões regulares.
    - Correção de pequenos erros ortográficos.

    A primeira chamada pode ser mais lenta devido à compilação inicial das expressões regulares.
    """

def padronizar_cep(valor: str) -> str:
    """
    Padroniza CEPs em formato textual para uma string formatada.

    Completa com zeros à esquerda quando necessário e retorna erro se o valor
    contiver caracteres inválidos ou exceder o tamanho permitido de CEP.

    Parameters
    ----------
    valor : str
        CEP em formato textual (ex: 12345-6, a123b45 6 sem os inválidos).

    Returns
    -------
    str
        CEP padronizado no formato XXXXX-XXX.

    Raises
    ------
    ValueError
        Se o CEP tiver caracteres inválidos ou muitos dígitos.

    Examples
    --------
    >>> import enderecobr
    >>> enderecobr.padronizar_cep('12345-6')
    '00123-456'

    """

def padronizar_cep_numerico(valor: int) -> str:
    """
    Padroniza um CEP numérico para uma string formatada.

    Completa com zeros à esquerda quando necessário e retorna erro se o valor
    exceder o tamanho permitido de CEP. O valor precisa ser inteiro e não
    negativo.

    Parameters
    ----------
    valor : int
        CEP em formato numérico (ex: 123456).

    Returns
    -------
    str
        CEP padronizado no formato XXXXX-XXX.

    Raises
    ------
    ValueError
        Se o CEP tiver muitos dígitos ou se o valor for negativo.

    Examples
    --------
    >>> import enderecobr
    >>> enderecobr.padronizar_cep_numerico(123456)
    '00123-456'

    """

def padronizar_cep_leniente(valor: str) -> str:
    """
    Padroniza CEPs em formato textual para uma string formatada, tentando corrigir possíveis erros.

    Esta função ignora quaisquer caracteres não numéricos, além de remover números
    extras e completar com zeros à esquerda quando necessário.

    Parameters
    ----------
    valor : str
        CEP em formato textual, que pode conter caracteres não numéricos e formatação irregular.

    Returns
    -------
    str
        CEP padronizado no formato XXXXX-XXX (com 8 dígitos, separados por hífen, completado com zeros à esquerda se necessário).

    Examples
    --------
    >>> import enderecobr
    >>> enderecobr.padronizar_cep_leniente("a123b45  6")
    '00123-456'

    Notes
    -----
    - São extraídos apenas os dígitos numéricos da entrada.
    - Se mais de 8 dígitos forem fornecidos, apenas os 8 primeiros são considerados.
    - Se menos de 8 dígitos forem fornecidos, zeros são adicionados à esquerda.
    """

class Padronizador:
    """
    Estrutura para padronização condicional de textos de endereços usando expressões regulares.

    Permite definir regras de substituição com condições de exclusão (``regex_ignorar``).
    Usa um conjunto de regex compilado para acelerar a detecção de padrões.

    Use `$1`, `$2`... para referenciar um grupo de captura na string de substituição.

    Por usar o motor de expressões regulares do Rust, esta classe **NÃO** aceita o uso de:

    - look-arounds -> ex: `^RUA(?!\\.)` (começa com "RUA", mas não deve ter um ponto após);
    - backreferences -> ex: `(\\w+) \\1` (duas palavras iguais repetidas após um espaço);


    Examples
    --------
    >>> from enderecobr import Padronizador
    >>> pad = Padronizador()
    >>> pad.adicionar_substituicoes([
    ...     ["AV ", "AVENIDA "],
    ...     ["^R ", "RUA ", "R APT"],
    ... ])
    >>> pad.padronizar("AV AZUL")
    'AVENIDA AZUL'
    >>> pad.padronizar("R APT AMARELA")
    'R APT AMARELA'

    """

    def __init__(self) -> None:
        """
        Inicializa um novo padronizador com nenhuma regra de substituição.
        """

    def adicionar_substituicoes(self, pares: Iterable[Iterable[None | str]]) -> None:
        """
        Adiciona múltiplas regras de substituição a partir de uma lista de listas.

        Cada sublista representa uma regra no formato:
        [regex, substituição, regex_ignorar] (valores None são ignorados).

        Regras:

        - 1 item: equivalente a [regex, '']
        - 2 itens: equivalente a [regex, substituição]
        - 3 ou mais itens: equivalente a [regex, substituição, regex_ignorar]

        Parameters
        ----------
        pares : list of list of (str or None)
            Lista de regras de substituição. Cada regra é uma lista com até três elementos.

        Examples
        --------
        >>> pad = Padronizador()
        >>> pad.adicionar_substituicoes([
        ...     ["R ", "RUA ", "APT R "],
        ...     ["AV ", "AVENIDA ", None],
        ...     ["NO ", "Nº"]
        ... ])

        """

    def padronizar(self, valor: str) -> str:
        """
        Aplica todas as regras de substituição ao texto, com normalização prévia.

        O texto é convertido para maiúsculas, acentos são removidos, e espaços
        extras são reduzidos. As regras são aplicadas em ordem, com condição de
        exclusão verificada antes de cada substituição.

        Parameters
        ----------
        valor : str
            Texto de entrada a ser padronizado.

        Returns
        -------
        str
            Texto padronizado.

        Examples
        --------
        >>> pad = Padronizador()
        >>> pad.adicionar_substituicoes([[r"\bR\b", "RUA"]])
        >>> pad.padronizar("  r amarela ")
        'RUA AMARELA'

        """

    def obter_substituicoes(self) -> list[tuple[str, str, None | str]]:
        """
        Retorna as regras de substituição atuais.

        Returns
        -------
        list of tuple of (str, str, str or None)
            Lista de triplas: (regex, substituição, regex_ignorar).

        Examples
        --------
        >>> pad = Padronizador()
        >>> pad.adicionar_substituicoes([["R ", "RUA "]])
        >>> pad.obter_substituicoes()
        [('R ', 'RUA ', None)]

        """

    def adicionar(self, regex: str, substituicao: str) -> None:
        r"""
        Adiciona uma regra simples de substituição.

        Toda ocorrência de ``regex`` será substituída por ``substituicao``.
        É necessário chamar ``Padronizador.preparar`` após adicionar regras
        manualmente para que passem a valer.

        Parameters
        ----------
        regex : str
            Expressão regular a ser substituída.
        substituicao : str
            Texto de substituição (use ``$1``, ``$2``... para grupos capturados).

        Examples
        --------
        >>> pad = Padronizador()
        >>> pad.adicionar(r'R\.', 'RUA')
        >>> pad.preparar()
        >>> pad.padronizar('R. AZUL')
        'RUA AZUL'

        """

    def adicionar_com_ignorar(
        self, regex: str, substituicao: str, regex_ignorar: str
    ) -> None:
        """
        Adiciona uma regra condicional de substituição (com regex de exclusão).

        ``regex`` é substituída por ``substituicao`` somente se ``regex_ignorar``
        não corresponder ao texto. É necessário chamar ``Padronizador.preparar``
        após adicionar regras manualmente.

        Parameters
        ----------
        regex : str
            Expressão regular a ser substituída.
        substituicao : str
            Texto de substituição.
        regex_ignorar : str
            Expressão regular de exclusão.

        Examples
        --------
        >>> pad = Padronizador()
        >>> pad.adicionar_com_ignorar(r'^R ', 'RUA ', r'R APT')
        >>> pad.preparar()
        >>> pad.padronizar('R AMARELA')
        'RUA AMARELA'
        >>> pad.padronizar('R APT AMARELA')
        'R APT AMARELA'

        """

    def adicionar_vetores(
        self,
        regexes: Iterable[str],
        substituicoes: Iterable[str],
        regex_ignorar: Iterable[None | str],
    ) -> None:
        """
        Adiciona regras a partir de três vetores paralelos.

        Os vetores devem ter o mesmo comprimento. O terceiro vetor pode conter
        None para indicar ausência de condição de exclusão. As regras são
        preparadas automaticamente ao término da execução.

        Parameters
        ----------
        regexes : iterable of str
            Expressões regulares a serem substituídas.
        substituicoes : iterable of str
            Textos de substituição correspondentes.
        regex_ignorar : iterable of (str or None)
            Expressões de exclusão correspondentes (ou None).

        Examples
        --------
        >>> pad = Padronizador()
        >>> pad.adicionar_vetores(['R ', 'AV '], ['RUA ', 'AVENIDA '], [None, None])
        >>> pad.padronizar('R AZUL')
        'RUA AZUL'

        """

    def preparar(self) -> None:
        r"""
        Recompila o conjunto de expressões regulares após adicionar regras manualmente.

        Deve ser chamado após ``Padronizador.adicionar`` ou
        ``Padronizador.adicionar_com_ignorar`` para que as novas regras
        passem a ser aplicadas.

        Examples
        --------
        >>> pad = Padronizador()
        >>> pad.adicionar(r'R\.', 'RUA')
        >>> pad.preparar()

        """

    def obter_vetores(self) -> tuple[list[str], list[str], list[None | str]]:
        """
        Retorna as regras como três vetores paralelos.

        Returns
        -------
        tuple of (list of str, list of str, list of (str or None))
            Vetores ``(regex, substituicao, ignorar)``.

        Examples
        --------
        >>> pad = Padronizador()
        >>> pad.adicionar_substituicoes([['R ', 'RUA ']])
        >>> pad.obter_vetores()
        (['R '], ['RUA '], [None])

        """

class IdentificadorPadroes:
    """
    Wrapper fino sobre um conjunto de expressões regulares compiladas para
    identificar rapidamente padrões em textos.

    Examples
    --------
    >>> from enderecobr import IdentificadorPadroes
    >>> idp = IdentificadorPadroes()
    >>> idp.adicionar(['RUA', 'AVENIDA'])
    >>> idp.identificar('RUA AZUL')
    True
    >>> idp.identificar('TRAVESSA')
    False

    """

    def __init__(self) -> None:
        """
        Inicializa um novo identificador de padrões, sem nenhuma regex cadastrada.
        """

    def adicionar(self, regexs: Iterable[str]) -> None:
        """
        Adiciona novas expressões regulares ao identificador.

        Parameters
        ----------
        regexs : iterable of str
            Lista de padrões regex a serem compilados e adicionados ao conjunto.

        Examples
        --------
        >>> idp = IdentificadorPadroes()
        >>> idp.adicionar(['RUA', 'AV'])

        """

    def identificar(self, valor: str) -> bool:
        """
        Verifica se alguma das regexes cadastradas corresponde ao valor.

        Parameters
        ----------
        valor : str
            Texto a ser verificado.

        Returns
        -------
        bool
            True se alguma regex corresponder, False caso contrário.

        Examples
        --------
        >>> idp = IdentificadorPadroes()
        >>> idp.adicionar(['RUA'])
        >>> idp.identificar('RUA AZUL')
        True
        >>> idp.identificar('AVENIDA')
        False

        """

def obter_padronizador_logradouros() -> Padronizador:
    """
    Obtém o padronizador utilizado internamente pela função `padronizar_logradouros`.
    Útil para adicionar padrões de substituição não incluídos originalmente.
    """

def obter_padronizador_numeros() -> Padronizador:
    """
    Obtém o padronizador utilizado internamente pela função `padronizar_numeros`.
    Útil para adicionar padrões de substituição não incluídos originalmente.
    """

def obter_padronizador_bairros() -> Padronizador:
    """
    Obtém o padronizador utilizado internamente pela função `padronizar_bairros`.
    Útil para adicionar padrões de substituição não incluídos originalmente.
    """

def obter_padronizador_complementos() -> Padronizador:
    """
    Obtém o padronizador utilizado internamente pela função `padronizar_complementos`.
    Útil para adicionar padrões de substituição não incluídos originalmente.
    """

def obter_padronizador_tipos_logradouros() -> Padronizador:
    """
    Obtém o padronizador utilizado internamente pela função `padronizar_tipo_logradouro`.
    Útil para adicionar padrões de substituição não incluídos originalmente.
    """

def metaphone(valor: str) -> str:
    """
    Gera um código fonético (Metaphone-BR adaptado) para nomes em português.

    Aplica transformações fonéticas a um nome visando representar sua pronúncia
    aproximada em português brasileiro. Útil para agrupar nomes com sonoridade
    similar, mesmo com grafias diferentes.

    Parameters
    ----------
    valor : str
        Nome ou texto a ser convertido em código fonético. Pode conter acentos,
        caracteres especiais, espaços e letras minúsculas.

    Returns
    -------
    str
        Código fonético em maiúsculas, com transformações aplicadas segundo regras
        adaptadas do Metaphone para o português brasileiro.

    Notes
    -----
    O processo inclui:

        - Remoção de acentos, números e conversão para maiúsculas;
        - Eliminação de letras silenciosas (ex: 'H' inicial);
        - Simplificação de dígrafos (ex: 'LH' → 'L', 'CH' → 'X');
        - Agrupamento de consoantes com sonoridade similar (ex: C/K/S, G/J);
        - Tratamento de sons nasais e vogais duplicadas;
        - Compactação de espaços e letras repetidas.

    Esta é uma adaptação que não segue rigorosamente nenhum algoritmo Metaphone
    publicado, mas foi inspirada neles, considerando o contexto do português brasileiro.

    Examples
    --------
    >>> enderecobr.metaphone("João Silva")
    'JOAO SILVA'
    >>> enderecobr.metaphone("Marya")
    'MARIA'
    >>> enderecobr.metaphone("Helena")
    'ELENA'
    >>> enderecobr.metaphone("Philippe")
    'FILIPE'
    >>> enderecobr.metaphone("Chavier")
    'XAVIER'
    >>> enderecobr.metaphone("Maçã")
    'MASA'

    """

def padronizar_numeros_por_extenso(valor: str) -> str:
    """
    Converte sequências de dígitos em uma string para seus equivalentes por extenso em português.

    A função percorre a string de entrada e, ao encontrar números inteiros (em formato ASCII),
    os substitui pelo nome completo do número (ex: "2" → "dois"), utilizando a função `numero_por_extenso`.

    Parameters
    ----------
    valor : str
        String de entrada que pode conter dígitos a serem convertidos.

    Returns
    -------
    str
        Nova string com dígitos convertidos por extenso. Retorna a string original se não houver dígitos.

    Notes
    -----
    - Números muito grandes ou inválidos (ex: overflow no parse para `i32`) são deixados inalterados.
    - Não trata números negativos ou decimais.
    - Se a string de entrada não contém nenhum dígito ASCII, retorna a string original.

    Examples
    --------
    >>> enderecobr.padronizar_numeros_por_extenso("RUA 2")
    'RUA DOIS'
    >>> enderecobr.padronizar_numeros_por_extenso("RUA -2")
    'RUA -DOIS'
    >>> enderecobr.padronizar_numeros_por_extenso("RUA -2.2")
    'RUA -DOIS.DOIS'
    >>> enderecobr.padronizar_numeros_por_extenso("Sem números")
    'Sem números'

    """

def padronizar_numero_romano_por_extenso(valor: str) -> str:
    """
    Substitui números romanos em um texto por suas representações por extenso (em palavras).
    Apenas sequências que formam números romanos válidos (1–3999) são convertidas.

    Parameters
    ----------
    valor : str
        Texto contendo números romanos a serem convertidos.

    Returns
    -------
    str
        Texto com números romanos substituídos por suas formas por extenso (maiúsculas).
        Retorna o texto original se nenhuma substituição for necessária.

    Examples
    --------
    >>> enderecobr.padronizar_numero_romano_por_extenso("Capítulo IX")
    'Capítulo NOVE'

    >>> enderecobr.padronizar_numero_romano_por_extenso("Séculos XV e XX")
    'Séculos QUINZE e VINTE'

    >>> enderecobr.padronizar_numero_romano_por_extenso("Rei João VI e Papa Bento XVI")
    'Rei João SEIS e Papa Bento DEZESSEIS'

    """

def numero_por_extenso(n: int) -> str:
    """
    Converte um número inteiro para sua representação por extenso em português.

    Retorna uma string com o número por extenso em letras maiúsculas.

    Parameters
    ----------
    n : int
        Número inteiro a ser convertido.

    Returns
    -------
    str
        Representação por extenso do número em português.

    Examples
    --------
    >>> enderecobr.numero_por_extenso(0)
    'ZERO'
    >>> enderecobr.numero_por_extenso(42)
    'QUARENTA E DOIS'
    >>> enderecobr.numero_por_extenso(-1500)
    'MENOS MIL E QUINHENTOS'
    >>> enderecobr.numero_por_extenso(2_001_000)
    'DOIS MILHOES E MIL'

    """

def romano_para_inteiro(valor: str) -> int:
    """
    Converte um número romano em sua representação por extenso (número inteiro).

    Aceita entradas em maiúsculas ou minúsculas. A conversão segue a regra padrão de números romanos,
    onde símbolos menores à esquerda de maiores são subtraídos. Suporta valores de 1 a 3999.

    Parameters
    ----------
    valor : str
        String contendo a representação de um número romano (ex: "IX", "MCMXC").

    Returns
    -------
    int
        Valor inteiro correspondente ao número romano. Retorna resultados inesperados se a string
        contiver caracteres inválidos (não tratados como erro).

    Examples
    --------
    >>> enderecobr.romano_para_inteiro("IX")
    9
    >>> enderecobr.romano_para_inteiro("xlII")
    42
    >>> enderecobr.romano_para_inteiro("MCMXC")
    1990
    >>> enderecobr.romano_para_inteiro("mmmcmxcix")
    3999

    Notes
    -----
    - Caracteres inválidos são tratados como 0 e podem gerar resultados inesperados.
    - A função não valida a correção gramatical da sequência romana (ex: "IIII" retorna 4).
    """

class TipoSegmento:
    """
    Tipo de informação que um trecho do endereço representa.

    As variantes são exatamente as mesmas do enum `TipoSegmento` do Rust, na
    mesma ordem, e cada uma se compara igual ao seu valor inteiro
    (``TipoSegmento.Cep == 12``, ``int(TipoSegmento.Cep) == 12``).

    Variantes, na ordem do enum:

    - [Logradouro][enderecobr.TipoSegmento.Logradouro]
    - [LogradouroInterno][enderecobr.TipoSegmento.LogradouroInterno]
    - [Numero][enderecobr.TipoSegmento.Numero]
    - [ModificadorNumero][enderecobr.TipoSegmento.ModificadorNumero]
    - [Complemento][enderecobr.TipoSegmento.Complemento]
    - [Empreendimento][enderecobr.TipoSegmento.Empreendimento]
    - [Parcela][enderecobr.TipoSegmento.Parcela]
    - [DescricaoArea][enderecobr.TipoSegmento.DescricaoArea]
    - [QuilometragemVia][enderecobr.TipoSegmento.QuilometragemVia]
    - [Referencia][enderecobr.TipoSegmento.Referencia]
    - [Denominacao][enderecobr.TipoSegmento.Denominacao]
    - [Localidade][enderecobr.TipoSegmento.Localidade]
    - [Cep][enderecobr.TipoSegmento.Cep]
    - [Municipio][enderecobr.TipoSegmento.Municipio]
    - [Uf][enderecobr.TipoSegmento.Uf]
    - [Outro][enderecobr.TipoSegmento.Outro]

    Examples
    --------
    >>> from enderecobr import TipoSegmento, SegmentoEndereco
    >>> segmento = SegmentoEndereco('123', TipoSegmento.Numero)
    >>> segmento.tipo == TipoSegmento.Numero
    True

    """

    Logradouro: TipoSegmento
    """Tipo de via + título + nome: `R ALCIDES CARNEIRO LEAL`, `ROD BR-116`."""

    LogradouroInterno: TipoSegmento
    """
    Via ou área interna de um empreendimento, fora do arruamento oficial.
    """

    Numero: TipoSegmento
    """Numeração predial, inclusive quando ausente: `71`, `S/N`."""

    ModificadorNumero: TipoSegmento
    """Sufixo ou marcador preso ao número: `A`, `504-B1`, `POSTE`."""

    Complemento: TipoSegmento
    """Unidade interna do imóvel, tipo e valor juntos: `APTO 104`, `BL 4`."""

    Empreendimento: TipoSegmento
    """
    Lugar nomeado: prédio, condomínio, conjunto, loteamento ou o próprio estabelecimento que ocupa o endereço: `ED MANAGUA`, `COND PALM VILLAGE`.
    """

    Parcela: TipoSegmento
    """
    Identificador cadastral do terreno (uma `gleba` pode conter uma `quadra` que pode conter um `lote`): `QD 34 LOTE 17`.
    """

    DescricaoArea: TipoSegmento
    """
    Descrição textual de área, seu uso ou medição; nunca um identificador. Ex.: `8.000,00 m²`, `ÁREA DE TERRA SITUADA NO LUGAR DENOMINADO...`, `MAR TERRITORIAL`, `MARGEM ESQUERDA`.
    """

    QuilometragemVia: TipoSegmento
    """
    Quilometragem em rodovia, onde o número é a posição ao longo da via: `KM 304`.
    """

    Referencia: TipoSegmento
    """
    Trecho que aponta para outro endereço ou lugar: `ESQUINA COM AV BOA VIAGEM`.
    """

    Denominacao: TipoSegmento
    """Nome atual ou antigo da via ou do lugar: `ANTIGA RUA B`."""

    Localidade: TipoSegmento
    """Localidade, bairro, distrito, vila ou zona: `PINA`, `ZONA RURAL`."""

    Cep: TipoSegmento
    """Código de endereçamento postal."""

    Municipio: TipoSegmento
    """Município."""

    Uf: TipoSegmento
    """Unidade federativa."""

    Outro: TipoSegmento
    """
    Conteúdo que não cabe em nenhum outro tipo — inclusive rótulo que ainda não tem variante própria.
    """

class SegmentoEndereco:
    """
    Um trecho do endereço e o atributo a que ele corresponde.

    Em geral os objetos vêm prontos de :func:`segmentar_endereco`, mas dá para
    montar um à mão — útil ao reidratar um ``segmento_como_json`` ou ao testar
    código que só lê os segmentos.

    Parameters
    ----------
    valor : str
        Trecho do endereço, sem os separadores originais.
    tipo : TipoSegmento
        Atributo do trecho.

    Attributes
    ----------
    valor : str
        Trecho do endereço, sem os separadores originais.
    tipo : TipoSegmento
        Atributo do trecho. Em JSON/dump sai como o rótulo em minúsculas
        (`logradouro`, `numero`, `complemento` etc.).

    Examples
    --------
    >>> from enderecobr import SegmentoEndereco, TipoSegmento
    >>> segmento = SegmentoEndereco('apt 301', TipoSegmento.Complemento)
    >>> (segmento.valor, segmento.tipo)
    ('apt 301', TipoSegmento.Complemento)
    >>> segmento.valor = 'apt 302'
    >>> segmento.tipo = TipoSegmento.Outro
    >>> (segmento.valor, segmento.tipo)
    ('apt 302', TipoSegmento.Outro)

    """

    def __init__(self, valor: str, tipo: TipoSegmento) -> None: ...

    valor: str
    tipo: TipoSegmento

class EnderecoSegmentado:
    """
    Resultado da segmentação de um endereço.

    Attributes
    ----------
    segmentos : list of SegmentoEndereco
        Segmentos na ordem em que aparecem no texto original.
    """

    segmentos: list[SegmentoEndereco]

class Endereco:
    """
    Endereço com os campos já separados.

    Pode ser criado vazio (``Endereco()``), com os campos que você já tem, ou
    obtido a partir de um texto com :func:`estruturar_endereco`. Campos ausentes
    ficam como ``None``.

    Attributes
    ----------
    logradouro : str or None
        Nome do logradouro (rua, avenida etc.).
    numero : str or None
        Número do imóvel; ``S/N`` quando não houver.
    complemento : str or None
        Complemento do imóvel (apartamento, bloco, loja etc.).
    localidade : str or None
        Bairro ou localidade.
    cep : str or None
        CEP no formato ``XXXXX-XXX``.

    Examples
    --------
    Montando um endereço a partir de campos soltos:

    >>> from enderecobr import Endereco
    >>> end = Endereco(logradouro='r. gen glicerio', numero='1')
    >>> end.padronizar()
    >>> end.logradouro
    'RUA GENERAL GLICERIO'

    """

    logradouro: str | None
    numero: str | None
    complemento: str | None
    localidade: str | None
    cep: str | None

    def __init__(
        self,
        logradouro: str | None = None,
        numero: str | None = None,
        complemento: str | None = None,
        localidade: str | None = None,
        cep: str | None = None,
    ) -> None:
        """
        Cria um endereço informando apenas os campos que existem.

        Parameters
        ----------
        logradouro : str or None, optional
            Nome do logradouro.
        numero : str or None, optional
            Número do imóvel.
        complemento : str or None, optional
            Complemento do imóvel.
        localidade : str or None, optional
            Bairro ou localidade.
        cep : str or None, optional
            CEP, que pode vir em qualquer formato (a padronização é feita
            depois, por :meth:`padronizar`).

        """

    def formatar(self) -> str:
        """
        Junta os campos preenchidos em um único texto, separados por vírgula.

        Campos ``None`` ou vazios são omitidos. É o mesmo texto devolvido por
        ``str(endereco)``.

        Returns
        -------
        str
            Texto com os campos preenchidos, na ordem logradouro, número,
            complemento, localidade e CEP.

        Examples
        --------
        >>> end = Endereco(logradouro='r. gen glicerio', numero='1')
        >>> end.formatar()
        'r. gen glicerio, 1'

        """

    def padronizar(self) -> None:
        """
        Padroniza os campos deste endereço no próprio objeto.

        Cada campo passa pela função adequada (logradouro, número,
        complemento, bairro e CEP). Campos vazios continuam vazios.

        Examples
        --------
        >>> end = Endereco(logradouro='r. gen glicerio', numero='1')
        >>> end.padronizar()
        >>> end.logradouro
        'RUA GENERAL GLICERIO'

        """

    def endereco_padronizado(self) -> Endereco:
        """
        Devolve uma cópia padronizada, sem alterar o original.

        Returns
        -------
        Endereco
            Novo endereço com os campos padronizados.

        Examples
        --------
        >>> end = Endereco(logradouro='r. gen glicerio', numero='1')
        >>> end.endereco_padronizado().logradouro
        'RUA GENERAL GLICERIO'
        >>> end.logradouro
        'r. gen glicerio'

        """

class SeparadorEndereco:
    """
    Segmentador probabilístico de endereços.

    Diferente das funções de módulo, permite usar um arquivo de modelo próprio
    em vez do modelo padrão. A instância nasce **sem modelo**: o construtor não lê nem baixa
    nada do disco. Use o método estático :meth:`carregar` ou o método :meth:`carregar_modelo`
    antes de :meth:`segmentar`. Depois de carregado, o separador não falha mais
    ao segmentar.

    Para usar o modelo padrão, obtenha o caminho com :func:`obter_modelo` (resolve e
    baixa, se necessário) ou com :func:`obter_caminho_modelo` (apenas resolve) e
    passe o retorno para :meth:`carregar`.

    Examples
    --------
    Usando o modelo padrão, sem precisar saber onde ele fica:

    >>> from enderecobr import SeparadorEndereco, obter_modelo
    >>> sep = SeparadorEndereco.carregar(obter_modelo())  # doctest: +SKIP
    >>> sep.segmentar('av n sra copacabana, 123').segmentos[0].tipo  # doctest: +SKIP
    TipoSegmento.Logradouro

    O construtor não carrega nada, o que permite criar a instância primeiro:

    >>> sep = SeparadorEndereco()
    >>> sep.carregar_modelo('/caminho/para/tagger.crf')  # doctest: +SKIP
    >>> sep.segmentar('av n sra copacabana, 123').segmentos[0].valor  # doctest: +SKIP
    'av n sra copacabana'

    """

    def __init__(self) -> None:
        """
        Inicializa um separador sem nenhum modelo carregado.
        """

    @staticmethod
    def carregar(caminho: str | Path) -> SeparadorEndereco:
        """
        Cria um separador já carregado a partir de um arquivo de modelo.

        Parameters
        ----------
        caminho : str or pathlib.Path
            Caminho do arquivo de modelo treinado.

        Returns
        -------
        SeparadorEndereco
            Separador pronto para uso.

        Raises
        ------
        RuntimeError
            Se o arquivo não existir, não puder ser lido ou não for um modelo válido.
        """

    def carregar_modelo(self, caminho: str | Path) -> None:
        """
        Carrega (ou substitui) o modelo desta instância, sem criar um objeto novo.

        Parameters
        ----------
        caminho : str or pathlib.Path
            Caminho do arquivo de modelo treinado.

        Raises
        ------
        RuntimeError
            Se o arquivo não existir, não puder ser lido ou não for um modelo válido.

        """

    def segmentar(self, texto: str) -> EnderecoSegmentado:
        """
        Segmenta o endereço nas suas partes constituintes.

        Parameters
        ----------
        texto : str
            Endereço bruto a ser segmentado.

        Returns
        -------
        EnderecoSegmentado
            Segmentos encontrados e seus atributos.

        Raises
        ------
        RuntimeError
            Se nenhum modelo tiver sido carregado antes da chamada.

        Notes
        -----
        O interpretador não é bloqueado durante a inferência: o GIL é liberado,
          portanto outras threads do Python seguem rodando.

        Examples
        --------
        >>> sep = enderecobr.SeparadorEndereco.carregar('/caminho/para/tagger.crf')  # doctest: +SKIP
        >>> seg = sep.segmentar('av n sra copacabana, 123, apt 301')  # doctest: +SKIP
        >>> [s.valor for s in seg.segmentos]  # doctest: +SKIP
        ['av n sra copacabana', '123', 'apt 301']

        """

    def segmentar_enderecos(self, textos: Iterable[str]) -> list[EnderecoSegmentado]:
        """
        Segmenta vários endereços de uma vez com o modelo desta instância.

        A saída mantém a ordem de entrada, e cada posição corresponde ao endereço
        de mesmo índice.

        Parameters
        ----------
        textos : iterable of str
            Endereços brutos a serem segmentados.

        Returns
        -------
        list of EnderecoSegmentado
            Um resultado por endereço, na mesma ordem da entrada.

        Raises
        ------
        RuntimeError
            Se nenhum modelo tiver sido carregado antes da chamada.

        Notes
        -----
        O GIL é liberado durante o processamento do lote inteiro.

        Examples
        --------
        >>> sep = enderecobr.SeparadorEndereco.carregar('/caminho/para/tagger.crf')  # doctest: +SKIP
        >>> resultados = sep.segmentar_enderecos(['av n sra copacabana, 123'])  # doctest: +SKIP
        >>> resultados[0].segmentos[0].tipo  # doctest: +SKIP
        'logradouro'

        """

def obter_caminho_modelo(path_modelo: str | Path | None = None) -> Path:
    """
    Resolve o caminho do modelo sem gravar nada no disco.

    Segue esta ordem de prioridade:

    1. ``path_modelo``, quando informado e não vazio;
    2. a variável de ambiente ``ENDERECOBR_MODELO``, quando definida e não vazia;
    3. o diretório de cache do sistema operacional (``~/.cache/...`` no Linux,
       ``~/Library/Caches`` no macOS, ``%LOCALAPPDATA%`` no Windows), no caminho
       ``enderecobr_rs/<versão do modelo>/tagger.crf``.

    Se o valor resolvido for um diretório (ou terminar em ``/``), o subdiretório
    da versão do modelo é acrescentado; se for um arquivo, ele é usado como está.

    Parameters
    ----------
    path_modelo : str or pathlib.Path or None, optional
        Arquivo ou diretório do modelo. Informado, tem prioridade sobre a
        variável de ambiente e sobre o cache.

    Returns
    -------
    pathlib.Path
        Caminho do arquivo que seria usado. O arquivo pode não existir.

    Raises
    ------
    RuntimeError
        Se nem o argumento nem ``ENDERECOBR_MODELO`` forem informados e o
        diretório de cache do sistema operacional não estiver disponível.

    Examples
    --------
    >>> enderecobr.obter_caminho_modelo('/tmp/modelos/').name
    'tagger.crf'
    >>> enderecobr.obter_caminho_modelo('/tmp/meu_modelo.crf').as_posix()
    '/tmp/meu_modelo.crf'

    Notes
    -----
    - Não acessa o disco nem a rede: só calcula o caminho.
    - É útil para inspecionar qual arquivo :func:`obter_modelo` usaria, antes de
      baixar qualquer coisa.

    """

def obter_modelo(path_modelo: str | Path | None = None) -> Path:
    """
    Resolve o caminho do modelo de padrão e garante que o arquivo exista,
    baixando-o na primeira chamada.

    Usa a mesma ordem de prioridade de :func:`obter_caminho_modelo` e só baixa o
    modelo quando o arquivo está ausente ou vazio. O download pode ser desativado
    com a variável de ambiente ``ENDERECOBR_MODELO_SEM_DOWNLOAD=1`` (útil em
    CI).

    Parameters
    ----------
    path_modelo : str or pathlib.Path or None, optional
        Arquivo ou diretório do modelo. Informado, tem prioridade sobre a
        variável de ambiente e sobre o cache.

    Returns
    -------
    pathlib.Path
        Caminho do arquivo ``.crf``, já existente.

    Raises
    ------
    RuntimeError
        Se o diretório de destino não puder ser criado, o download falhar ou o
        arquivo não puder ser gravado.

    Examples
    --------
    >>> from enderecobr import SeparadorEndereco, obter_modelo
    >>> sep = SeparadorEndereco.carregar(obter_modelo())  # doctest: +SKIP
    >>> sep.segmentar('av n sra copacabana, 123').segmentos[0].tipo  # doctest: +SKIP
    'logradouro'

    Notes
    -----
    - Faz uma requisição HTTP (timeout de 60 s) apenas quando precisa baixar e
      libera o GIL durante a operação.
    - O caminho devolvido pode ser passado direto para :meth:`SeparadorEndereco.carregar`.

    """

def segmentar_endereco(endereco: str) -> EnderecoSegmentado:
    """
    Segmenta um endereço usando o modelo padrão, compartilhado entre chamadas.

    Usa o modelo resolvido por `ENDERECOBR_MODELO` ou o cache do sistema
    (baixando-o na primeira chamada, se necessário). Para usar um modelo próprio,
    prefira :class:`SeparadorEndereco`.

    Para saber (ou controlar) qual arquivo é esse, veja :func:`obter_caminho_modelo`
    (resolve o caminho sem tocar no disco) e :func:`obter_modelo` (resolve e baixa).

    Parameters
    ----------
    endereco : str
        Endereço bruto a ser segmentado.

    Returns
    -------
    EnderecoSegmentado
        Segmentos encontrados e seus atributos.

    Raises
    ------
    RuntimeError
        Se o modelo padrão não puder ser obtido ou carregado.

    Examples
    --------
    >>> seg = enderecobr.segmentar_endereco('av n sra copacabana, 123')  # doctest: +SKIP
    >>> [(s.valor, s.tipo) for s in seg.segmentos]  # doctest: +SKIP
    [('av n sra copacabana', TipoSegmento.Logradouro), ('123', TipoSegmento.Numero)]

    Notes
    -----
    O GIL é liberado durante a inferência, então outras threads do Python
    seguem rodando.

    """

def segmentar_enderecos(enderecos: Iterable[str]) -> list[EnderecoSegmentado]:
    """
    Segmenta vários endereços de uma vez com o modelo padrão.

    É a forma mais eficiente de processar uma lista ou uma coluna de endereços:
    o modelo é carregado uma única vez e o interpretador não é bloqueado durante
    o processamento.

    A saída mantém a ordem de entrada, e cada posição corresponde ao endereço de
    mesmo índice.

    Parameters
    ----------
    enderecos : iterable of str
        Endereços brutos a serem segmentados.

    Returns
    -------
    list of EnderecoSegmentado
        Um resultado por endereço, na mesma ordem da entrada.

    Raises
    ------
    RuntimeError
        Se o modelo padrão não puder ser obtido ou carregado.

    Examples
    --------
    >>> resultados = enderecobr.segmentar_enderecos([  # doctest: +SKIP
    ...     'av n sra copacabana, 123',
    ...     'r das flores, 45, apt 12',
    ... ])
    >>> len(resultados)  # doctest: +SKIP
    2

    """

def estruturar_endereco(endereco: str, padronizar: bool = True) -> Endereco:
    """
    Segmenta o endereço e devolve os campos já separados em um :class:`Endereco`.

    Atalho para segmentar e depois agrupar os trechos nos campos do endereço.
    Use :func:`segmentar_endereco` quando quiser ver os trechos e seus tipos.

    Parameters
    ----------
    endereco : str
        Endereço bruto a ser estruturado.
    padronizar : bool, optional
        Se ``True`` (padrão), os campos resultantes passam pelas funções de
        padronização.

    Returns
    -------
    Endereco
        Endereço com os campos encontrados.

    Raises
    ------
    RuntimeError
        Se o modelo padrão não puder ser obtido ou carregado.

    Examples
    --------
    >>> end = enderecobr.estruturar_endereco('av n sra copacabana, 123')  # doctest: +SKIP
    >>> end.numero  # doctest: +SKIP
    '123'

    """
