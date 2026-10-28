"""Normalizacao e tokenizacao do texto do endereco."""

import unicodedata

import regex

MARCADORES_CONHECIDOS_DF = {
    "SQN",
    "SQS",
    "SQNW",
    "SQSW",
    "SCLN",
    "SCLS",
    "SCN",
    "SCS",
    "SGAN",
    "SGAS",
    "SEPN",
    "SEPS",
    "SRTVN",
    "SRTVS",
    "SHN",
    "SHS",
    "SHIS",
    "SHIN",
    "SHLS",
    "SHLN",
    "SHCGN",
    "SHCES",
    "SHCE",
    "SHTQ",
    "SMPW",
    "SAAN",
    "SAS",
    "SAUS",
    "SAUN",
    "SBS",
    "SDS",
    "SDN",
    "SDMC",
    "SIG",
    "SIA",
    "SIBS",
    "SCES",
    "SMHN",
    "SMLN",
    "SRES",
    "SRL",
    "SO",
    "SOPI",
    "SOFS",
    "CLN",
    "CLS",
    "CLNW",
    "ADE",
    "AOS",
    "AR",
    "CCSW",
    "CSG",
    "CRS",
    "CSA",
    "CSB",
    "CSD",
    "CNB",
    "CND",
    "CNG",
    "CNL",
    "CNM",
    "EQ",
    "EQNM",
    "EQNO",
    "EQNP",
    "EQS",
    "QI",
    "QE",
    "QS",
    "QR",
    "QN",
    "QD",
    "QNM",
    "QNN",
    "QNO",
    "QNP",
    "QNA",
    "QNC",
    "QND",
    "QNE",
    "QNF",
    "QNG",
    "QNH",
    "QNJ",
    "QNL",
    "QMS",
    "QMSW",
    "QRC",
    "QRSW",
    "QSB",
    "QSC",
    "QSE",
    "QRO",
    "SIND",
    "SGCV",
    "SCE",
}

MARCADORES_CONHECIDOS_PALMAS = {
    # Residenciais (quadrantes)
    "ARSE",
    "ARSO",
    "ARNE",
    "ARNO",
    # Comércio e serviço
    "AC",
    "ACSE",
    "ACSO",
    "ACNE",
    "ACNO",
    "ACSU",
    "ACSV",
    "ASR",
    # Administrativas
    "AA",
    "AAF",
    "AAE",
    "AAM",
    "AANE",
    "AANO",
    "AASE",
    "AASO",
    # Especiais / lazer / verde
    "AE",
    "ALC",
    "AVNE",
    "AVNO",
    "AVSE",
    "AVSO",
    # Públicas / moradia
    "APM",
    "HM",
    # Subdivisões internas (quadra interna)
    "QI",
    "QD",
    "QR",
    "QC",
    # Vias estruturais
    "LO",
    "NS",
}

SIGLAS_ESTADOS = {
    "AC",
    "AL",
    "AP",
    "AM",
    "BA",
    "CE",
    "DF",
    "ES",
    "GO",
    "MA",
    "MT",
    "MS",
    "MG",
    "PA",
    "PB",
    "PR",
    "PE",
    "PI",
    "RJ",
    "RN",
    "RS",
    "RO",
    "RR",
    "SC",
    "SP",
    "SE",
    "TO",
}

PADRAO_TOKEN = regex.compile(r"\p{N}+|\p{L}+|[^\s\p{L}\p{N}]")


def tokenize(text: str) -> list[str]:
    return PADRAO_TOKEN.findall(text)


def tokenize_com_offsets(text: str) -> list[tuple[str, int]]:
    """Tokens junto do offset (em caracteres) onde cada um começa em `text`.

    O offset é o que permite remontar os segmentos preservando o texto bruto,
    como o `SeparadorEndereco::segmentar` do Rust faz.
    """
    return [(m.group(0), m.start()) for m in PADRAO_TOKEN.finditer(text)]


def normalize(text: str):
    normalized = unicodedata.normalize("NFKD", text)
    return "".join([c for c in normalized if c.isascii()])


PONTUACAO = frozenset("!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~¨´°§¶·«»–—…“”‘’")


def is_pontuacao(word: str) -> bool:
    return bool(word) and word[0] in PONTUACAO
