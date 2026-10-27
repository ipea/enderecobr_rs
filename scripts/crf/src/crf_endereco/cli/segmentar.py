"""Comando que segmenta um endereco avulso."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from crf_endereco.config import CAMINHO_TAGGER
from crf_endereco.features import ExtratorFeature
from crf_endereco.modelos import inferencia


def segmentar(
    tagger: Annotated[Path, typer.Option(help="tagger treinado")] = CAMINHO_TAGGER,
) -> None:
    """Le enderecos do stdin e imprime os segmentos previstos."""
    crf = inferencia.carregar_tagger(tagger)
    extrator = ExtratorFeature()

    while True:
        try:
            linha = input()
        except EOFError:
            break
        if not linha:
            continue
        print("-----------------")
        for segmento in inferencia.segmentar(crf, extrator, linha):
            print(f"{segmento.get('tipo', '').title()}: {segmento.get('valor', '')}")
