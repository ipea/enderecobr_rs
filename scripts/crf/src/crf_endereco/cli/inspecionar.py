"""Comando que inspeciona os pesos do tagger."""

from __future__ import annotations

import collections
from pathlib import Path
from typing import Annotated

import typer

from crf_endereco.config import CAMINHO_TAGGER
from crf_endereco.modelos.inferencia import carregar_tagger


def inspecionar(
    tagger: Annotated[Path, typer.Argument(help="Path do tagger treinado")] = (
        CAMINHO_TAGGER
    ),
    output: Annotated[
        Path | None, typer.Option("--output", "-o", help="Path do resultado")
    ] = None,
) -> None:
    """Lista os pesos aprendidos por atributo e rotulo."""
    crf = carregar_tagger(tagger)
    features = collections.Counter(crf.state_features_).most_common()

    if output is None:
        for (attr, label), weight in features:
            print(f"{weight:0.6f} {label:<8} {attr}")
        return
    try:
        with open(output, "w", encoding="utf-8") as arquivo:
            for (attr, label), weight in features:
                arquivo.write(f"{weight:0.6f} {label:<8} {attr}\n")
    except OSError as erro:
        raise typer.BadParameter(f"nao foi possivel escrever {output}: {erro}") from erro
