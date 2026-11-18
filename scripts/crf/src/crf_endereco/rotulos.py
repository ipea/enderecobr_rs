"""Alinhamento dos segmentos da LLM com os tokens do CRF (BIO)."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from crf_endereco.features import is_pontuacao

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


def alinhamento(
    endereco: str,
    segmentos: list[dict[str, str]],
    tokenizer: Callable[[str], list[str]],
) -> tuple[list[str], list[str], list[str]]:
    """Tokens, rotulos BIO e o que sobrou de segmento sem token correspondente.

    O terceiro item denuncia palavra colada na base de origem (`CARAMURUANTIGA`):
    o segmento e verbatim como texto, mas nao existe como token, entao o
    ponteiro trava e o resto do endereco vira `O` em silencio. Quem treina
    prefere descartar a linha inteira a ensinar que esse resto e fundo.

    A pontuacao que abre um segmento marca o corte e nao pertence ao trecho: sai
    da linha e cai em `O`, que e o rotulo dela quando esta entre dois trechos. O
    mesmo nao vale no fim, onde ela pode ser da propria abreviacao (`AP.`) ou do
    marcador (`C/`).
    """
    toks_segmentos: list[tuple[str, str]] = []

    for segmento in segmentos:
        texto_segmento = segmento.get("valor", "")
        tipo_segmento = segmento.get("tipo", "")
        rotulo = mapa_tipo_segmento.get(tipo_segmento, tipo_segmento)
        toks_segmento = tokenizer(texto_segmento)
        while toks_segmento and is_pontuacao(toks_segmento[0]):
            toks_segmento.pop(0)
        for i, tok in enumerate(toks_segmento):
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
    residuo = [tok for tok, _ in toks_segmentos[pos_segmento:]]
    return toks_endereco, toks_labels, residuo


def mergear(
    endereco: str,
    segmentos: list[dict[str, str]],
    tokenizer: Callable[[str], list[str]],
) -> tuple[list[str], list[str]]:
    """Converte os segmentos verbatim em rotulos BIO alinhados aos tokens."""
    toks_endereco, toks_labels, _ = alinhamento(endereco, segmentos, tokenizer)
    return toks_endereco, toks_labels
