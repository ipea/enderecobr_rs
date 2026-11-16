"""Alinhamento dos segmentos da LLM com os tokens do CRF (BIO)."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass

# Tradução tipo da anotação -> rótulo do treino. Ausente do mapa = treina com o
# próprio tipo; `None` = não treina (o token vira `O`).
mapa_tipo_segmento: dict[str, str | None] = {
    "cadastro": None,
    "ruido": None,
    "outros": None,
}

# Veredito de uma reetiquetacao: o que a resposta nova fez com a divergencia.
CONCORDA_COM_O_CRF = "concorda com o CRF"
ROTULO_MANTIDO = "rótulo mantido"
ROTULO_NOVO = "rótulo novo"


@dataclass(frozen=True)
class Mudanca:
    """Um token em que as tres etiquetas de um endereco nao batem.

    `antes` e a etiqueta anterior a reetiquetacao, `previsto` a do CRF e
    `agora` a da resposta mais recente da LLM.
    """

    token: str
    antes: str
    previsto: str
    agora: str


def comparar(
    tokens: Sequence[str],
    antes: Sequence[str],
    previsto: Sequence[str],
    agora: Sequence[str],
) -> tuple[list[Mudanca], str]:
    """Tokens em que as tres etiquetas nao batem, e o veredito do endereco.

    O veredito le o que a etiqueta nova fez com o caso: repetiu a de antes (quem
    carrega o erro e o modelo), passou a concordar com o CRF (a de antes era o
    problema) ou inventou uma terceira.
    """
    mudancas = [
        Mudanca(token, anterior, crf, novo)
        for token, anterior, crf, novo in zip(
            tokens, antes, previsto, agora, strict=True
        )
        if not anterior == crf == novo
    ]
    if not mudancas:
        return [], CONCORDA_COM_O_CRF
    if all(mudanca.antes == mudanca.agora for mudanca in mudancas):
        return mudancas, ROTULO_MANTIDO
    if all(mudanca.previsto == mudanca.agora for mudanca in mudancas):
        return mudancas, CONCORDA_COM_O_CRF
    return mudancas, ROTULO_NOVO


def mergear(
    endereco: str,
    segmentos: list[dict[str, str]],
    tokenizer: Callable[[str], list[str]],
) -> tuple[list[str], list[str]]:
    """Converte os segmentos verbatim em rotulos BIO alinhados aos tokens."""
    toks_segmentos: list[tuple[str, str]] = []

    for segmento in segmentos:
        texto_segmento = segmento.get("valor", "")
        tipo_segmento = segmento.get("tipo", "")
        rotulo = mapa_tipo_segmento.get(tipo_segmento, tipo_segmento)
        for i, tok in enumerate(tokenizer(texto_segmento)):
            if rotulo is None:
                toks_segmentos.append((tok, "O"))
            else:
                prefixo = "B" if i == 0 else "I"
                toks_segmentos.append((tok, f"{prefixo}_{rotulo.upper()}"))

    toks_endereco = tokenizer(endereco)
    toks_labels: list[str] = []
    pos_segmento = 0

    for tok in toks_endereco:
        if pos_segmento < len(toks_segmentos):
            seg_atual = toks_segmentos[pos_segmento]
        else:
            seg_atual = None

        if seg_atual is not None and tok == seg_atual[0]:
            toks_labels.append(seg_atual[1])
            pos_segmento += 1
        else:
            toks_labels.append("O")

    assert len(toks_labels) == len(toks_endereco)
    return toks_endereco, toks_labels
