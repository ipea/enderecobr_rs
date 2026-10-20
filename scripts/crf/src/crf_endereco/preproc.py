import unicodedata
from collections.abc import Iterable

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


class ExtratorFeature:
    def __init__(self, distancias_vizinhaca: Iterable[int] = (-2, -1, 1, 2)) -> None:
        self.distancias_vizinhaca: Iterable[int] = distancias_vizinhaca

    def sent2features(self, text: str) -> list[dict[str, float]]:
        toks = tokenize(text)
        return self.tokens2features(toks)

    # uso direto quando já tokenizado
    def tokens2features(self, toks: list[str]) -> list[dict[str, float]]:
        return [
            dict.fromkeys(self._features_posicao(toks, i), 1.0)
            for i in range(len(toks))
        ]

    def _features_posicao(self, sent: list[str], i: int) -> list[str]:
        """Gerador de features principal, baseado somente na posição do token solicitado e seus vizinhos."""
        feats: list[str] = []
        feats.append("bias")
        feats.append(f"{int(i / len(sent) * 4)}_pos")
        feats += self._features_token(sent[i], "0")

        if i == 0:
            feats.append("BOS")

        if i == len(sent) - 1:
            feats.append("EOS")

        for distancia in self.distancias_vizinhaca:
            feats += self._features_vizinhanca(
                sent, indice_inicial=i, distancia=distancia
            )

        return feats

    def _features_token(self, token: str, prefixo: str) -> list[str]:
        """Gerador de feature para um token específico.

        A ordem e o critério de classificação espelham o `ExtratorFeature` do
        Rust (`src/separador_endereco.rs`), que é a implementação de referência.
        """
        token = normalize(token).upper().strip()

        # `tam` usa o comprimento sem zeros à esquerda: "000123" e "123" caem
        # no mesmo bucket. O Rust abandonou a feature `digit_len`.
        sem_zeros = token.lstrip("0") if token.isdigit() else token
        tam_palavra = min(len(sem_zeros), 10)

        feats: list[str] = [token, f"tam:{tam_palavra}"]

        if token in MARCADORES_CONHECIDOS_DF:
            feats.append("marcador_df")
        if token in MARCADORES_CONHECIDOS_PALMAS:
            feats.append("marcador_palmas")
        if token in SIGLAS_ESTADOS:
            feats.append("sigla_estado")

        if len(token) == 0:
            # Provavelmente a palavra foi removida pelo normalize
            feats.append("is_unknown")
        elif is_pontuacao(token):
            feats.append("is_punct")
            # O tokenizador emite uma pontuação por token; o Rust trunca para um
            # caractere por segurança e aqui seguimos a mesma regra.
            feats[0] = token[0]
        elif token.isdigit():
            feats.append("is_digit")
        elif token.isalpha():
            feats.append("is_alpha")
        else:
            # Alcança os alfanuméricos, que o tokenizador nunca gera (ele separa
            # letras de números) e que o Rust também trata como desconhecidos.
            feats.append("is_unknown")

        return [f"{prefixo}:{f}" for f in feats]

    def _features_vizinhanca(
        self, sent: list[str], indice_inicial: int, distancia: int
    ) -> list[str]:
        # Distância zero não faz sentido
        assert distancia != 0

        # direção da busca de novas palavras
        direcao = 1 if distancia > 0 else -1

        # Chamo seguidamente a função de localizar a próxima palavra para casos
        # que desejo de vizinhos mais distantes.
        posicao_vizinho: int | None = indice_inicial
        posicao_vizinho_anterior: int | None = None
        for _ in range(abs(distancia)):
            if posicao_vizinho is not None:
                posicao_vizinho_anterior = posicao_vizinho
                posicao_vizinho = self._pos_prox_palavra(sent, posicao_vizinho, direcao)

        if posicao_vizinho is None:
            return []

        feats: list[str] = []
        # Prefixo com o sinal do próprio inteiro ("1", "-1"): igual ao Rust, evita
        # uma concatenação por token e mantém as duas implementações idênticas.
        sufixo = str(distancia)

        feats += self._features_token(sent[posicao_vizinho], sufixo)

        # Caso o vizinho solicitado não esteja na posição esperada, algum token
        # (tipicamente pontuação) foi pulado pela busca de próxima palavra.
        if (
            posicao_vizinho != indice_inicial + distancia
            and posicao_vizinho_anterior is not None
        ):
            inicio = min(posicao_vizinho_anterior, posicao_vizinho)
            fim = max(posicao_vizinho_anterior, posicao_vizinho)
            if any(is_pontuacao(tok) for tok in sent[inicio : fim + 1]):
                feats.append(f"tem_pontuacao:{sufixo}")

        return feats

    def _pos_prox_palavra(
        self, sent: list[str], indice_inicial: int, direcao: int
    ) -> int | None:
        i = indice_inicial + direcao
        while i >= 0 and i < len(sent):
            tok = sent[i]
            # Alfabético ou numérico
            if tok.isalnum():
                return i
            i += direcao
