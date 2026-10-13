import re
from dataclasses import asdict
from collections.abc import Iterable
from typing import Callable

from crf_endereco.endereco import Endereco

import unicodedata


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


def tokenize(text: str):
    return re.findall(r"\d+|\w+|[^\s\w]", text)


class RotuladorEnderecoBIO:
    map_tags: dict[str, str] = {
        "logradouro": "LOG",
        "numero": "NUM",
        "complemento": "COM",
        "bairro": "LOC",
        "municipio": "MUN",
        "cep": "CEP",
    }

    def __init__(self, tokenizer: Callable[[str], list[str]]):
        self.tokenizer: Callable[[str], list[str]] = tokenizer

    def obter_tokenizado(self, endereco: Endereco) -> tuple[list[str], list[str]]:
        tokens: list[str] = []
        targets: list[str] = []

        ordem_campos = endereco.formato.split(" ")
        separador_toks = self.tokenizer(endereco.separador)
        tam_separador = len(separador_toks)

        # Transforma num dicionario para facilitar manipulação
        reg = {
            k: v.upper() if isinstance(v, str) else v
            for k, v in asdict(endereco).items()
        }

        for campo in ordem_campos:
            valor_campo = reg.get(campo)
            tag_atual = self.map_tags.get(campo)

            if not valor_campo or not tag_atual:
                continue

            # Adiciona separador no fim antes de adicionar os novos tokens,
            # senão estiver no início e se o separador "existir"
            if len(tokens) and tam_separador:
                tokens += separador_toks
                targets += ["O"] * tam_separador

            tokens_atuais = self.tokenizer(valor_campo)
            targets_atuais = [f"I-{tag_atual}"] * len(tokens_atuais)
            targets_atuais[0] = f"B-{tag_atual}"

            tokens += tokens_atuais
            targets += targets_atuais

        return tokens, targets


def normalize(text: str):
    normalized = unicodedata.normalize("NFKD", text)
    return "".join([c for c in normalized if c.isascii()])


def is_pontuacao(word: str) -> bool:
    if len(word) == 0:
        return False
    return word[0] in ",.;/:?!@#$%¨&*()-+[]{}\"'\\|"


class ExtratorFeature:
    def __init__(self, distancias_vizinhaca: Iterable[int] = (-2, -1, 1, 2)) -> None:
        self.distancias_vizinhaca: Iterable[int] = distancias_vizinhaca

    def sent2features(self, text: str) -> list[dict[str, float]]:
        toks = tokenize(text)
        return self.tokens2features(toks)

    # uso direto quando já tokenizado
    def tokens2features(self, toks: list[str]) -> list[dict[str, float]]:
        return [
            {feat: 1.0 for feat in self._features_posicao(toks, i)}
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
        """Gerador de feature para um token específico."""
        feats: list[str] = []
        token = normalize(token).upper().strip()
        feats.append(token)

        tam_palavra = len(token)
        if tam_palavra >= 7:
            tam_palavra = "7+"
        feats.append(f"tam:{tam_palavra}")

        if token in MARCADORES_CONHECIDOS_DF:
            feats.append("marcador_df")
        if token in SIGLAS_ESTADOS:
            feats.append("sigla_estado")

        if len(token) == 0:
            # Provavelmente a palavra foi removida pelo normalize
            feats.append("is_unknown")
        elif is_pontuacao(token):
            feats.append("is_punct")
            # Não acontece na prática de ter mais de uma pontuação por token,
            # mas o tokenizador em si pode mudar e isso virar um erro silencioso.
            feats.remove(token)
            feats.append(token[0])
        elif token.isdigit():
            feats.remove(token)
            token = re.sub("^0+", "", token)
            feats.append("is_digit")
            tam_palavra = len(token)
            if tam_palavra >= 7:
                tam_palavra = "7+"
            feats.append(f"digit_len:{tam_palavra!s}")
        elif token.isalnum():
            feats.append("is_alpha")
            if any(char.isdigit() for char in token):
                feats.append("has_digit")
        else:
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
        sinal = "+" if direcao == 1 else "-"
        sufixo = f"{sinal}{abs(distancia)}"

        feats += self._features_token(sent[posicao_vizinho], sufixo)

        # Caso o vizinho solicitado não seja na posição esperada
        if posicao_vizinho != indice_inicial + distancia:
            tem_pontuacao = [
                is_pontuacao(tok)
                for tok in sent[posicao_vizinho_anterior:posicao_vizinho]
            ]
            if tem_pontuacao:
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
