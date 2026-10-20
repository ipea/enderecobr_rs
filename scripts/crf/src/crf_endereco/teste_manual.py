from pathlib import Path
from typing import Annotated

import sklearn_crfsuite
import typer

from crf_endereco.preproc import ExtratorFeature, tokenize_com_offsets

# `str.isspace()` é mais amplo que o `u8::is_ascii_whitespace` usado pelo Rust
# (inclui NBSP, por exemplo); o conjunto explícito mantém as duas
# implementações equivalentes.
ESPACOS_ASCII = frozenset(" \t\n\x0c\r")


def montar_segmentos(
    frase: str,
    tokens_com_offset: list[tuple[str, int]],
    tags: list[str],
) -> list[dict[str, str]]:
    """Remonta os segmentos a partir dos rótulos BIO.

    Espelha `SeparadorEndereco::segmentar` do Rust (`src/separador_endereco.rs`):
    o separador entre tokens de um mesmo segmento vem do texto bruto, ou seja,
    só entra um espaço quando o caractere anterior ao token é espaço em branco.
    Assim "S/N" e "310A" continuam verbatim em vez de virar "S / N" e "310 A".
    """
    segmentos: list[dict[str, str]] = []

    for (tok, offset), tag in zip(tokens_com_offset, tags, strict=True):
        partes = tag.split("_", 1)
        if len(partes) != 2:
            continue  # "O": token fora de qualquer segmento

        bio, tipo = partes
        tipo = tipo.lower()

        if bio == "B":
            segmentos.append({"tipo": tipo, "valor": tok})
        elif bio == "I":
            if not segmentos or segmentos[-1]["tipo"] != tipo:
                continue
            if offset > 0 and frase[offset - 1] in ESPACOS_ASCII:
                segmentos[-1]["valor"] += " "
            segmentos[-1]["valor"] += tok

    return segmentos


def extrair_campos(
    crf: sklearn_crfsuite.CRF, extrator: ExtratorFeature, frase: str
) -> list[tuple[str, str]]:
    """Tokens e rótulos previstos pelo CRF para a frase."""
    toks = tokenize_com_offsets(frase)
    x = extrator.tokens2features([tok for tok, _ in toks])
    pred = crf.predict_single(x)

    return list(zip([tok for tok, _ in toks], pred, strict=True))


def segmentar(
    crf: sklearn_crfsuite.CRF, extrator: ExtratorFeature, frase: str
) -> list[dict[str, str]]:
    """Pipeline completo do Rust (`segmentar_endereco`) para uma frase."""
    tokens_com_offset = tokenize_com_offsets(frase)
    x = extrator.tokens2features([tok for tok, _ in tokens_com_offset])
    tags = crf.predict_single(x)

    return montar_segmentos(frase, tokens_com_offset, tags)


app = typer.Typer(no_args_is_help=True, add_completion=False)


@app.command()
def main(
    tagger: Annotated[Path, typer.Argument(help="Path do tagger treinado")] = Path(
        "./tagger.crf"
    ),
):
    # Por algum motivo, basta só importar isso para a função
    # input funcionar adequadamente.
    import readline as _

    crf = sklearn_crfsuite.CRF(model_filename=str(tagger))
    extrator = ExtratorFeature()

    while True:
        try:
            line = input()
        except EOFError:
            break
        if not line:
            continue
        segmentos = segmentar(crf, extrator, line)

        print("-----------------")
        for seg in segmentos:
            print(f"{seg.get('tipo', '').title()}: {seg.get('valor', '')}")
        print("=================")


if __name__ == "__main__":
    app()
