"""Comando de avaliacao do CRF."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from crf_endereco.config import CAMINHO_DATASET, CAMINHO_TAGGER
from crf_endereco.modelos import avaliacao
from crf_endereco.modelos.treino import carregar_exemplos


def avaliar(
    dataset: Annotated[Path, typer.Option(help="banco de anotacao")] = CAMINHO_DATASET,
    tagger: Annotated[Path, typer.Option(help="tagger treinado")] = CAMINHO_TAGGER,
) -> None:
    """Avalia o CRF por token e por classe."""
    exemplos = carregar_exemplos(dataset)
    avaliacao.avaliar(
        exemplos.x, exemplos.y, exemplos.categorias, exemplos.tokens, tagger
    )
