"""Alinhamento dos segmentos da LLM com os tokens do CRF (BIO)."""

from collections.abc import Callable

# Tradução tipo da anotação -> rótulo do treino. Ausente do mapa = treina com o
# próprio tipo; `None` = não treina (o token vira `O`).
mapa_tipo_segmento: dict[str, str | None] = {
    "cadastro": None,
    "ruido": None,
    "outros": None,
}


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
        for i, tok in enumerate(tokenizer(texto_segmento)):
            if tipo_segmento in mapa_tipo_segmento:
                tipo_segmento = mapa_tipo_segmento[tipo_segmento]

            if tipo_segmento is None:
                toks_segmentos.append((tok, "O"))
            elif i == 0:
                toks_segmentos.append((tok, f"B_{tipo_segmento.upper()}"))
            else:
                toks_segmentos.append((tok, f"I_{tipo_segmento.upper()}"))

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
