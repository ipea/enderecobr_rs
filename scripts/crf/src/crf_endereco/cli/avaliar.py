"""Comando de avaliacao do CRF."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from crf_endereco.config import CAMINHO_DATASET, CAMINHO_TAGGER
from crf_endereco.features import ExtratorFeature, tokenize
from crf_endereco.modelos import avaliacao
from crf_endereco.rotulos import mergear


def avaliar(
    dataset: Annotated[Path, typer.Option(help="banco de anotacao")] = CAMINHO_DATASET,
    tagger: Annotated[Path, typer.Option(help="tagger treinado")] = CAMINHO_TAGGER,
) -> None:
    """Avalia o CRF por token e por classe."""
    dados = avaliacao.consulta_duckdb(
        """
        select endereco, resposta_llm, origem, uf
        from enderecos
        where resposta_llm is not null
          and (resposta_llm ->> '$.erro') is null;
        """,
        dataset,
    )

    extrator = ExtratorFeature()
    x: list[list[dict[str, float]]] = []
    y: list[list[str]] = []
    categorias: list[list[str]] = []
    tokens: list[list[str]] = []

    for endereco, resposta_str, origem, uf in dados:
        try:
            resposta = json.loads(resposta_str)
        except json.JSONDecodeError as erro:
            raise typer.BadParameter(
                f"resposta invalida no endereco {endereco!r}: {erro}"
            ) from erro
        toks, labels = mergear(endereco, resposta.get("segmentos", []), tokenize)
        x.append(extrator.tokens2features(toks))
        y.append(labels)
        categorias.append([origem, uf])
        tokens.append(toks)

    avaliacao.avaliar(x, y, categorias, tokens, tagger)
