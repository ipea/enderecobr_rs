"""Comando que compara a segmentacao do Python com a do Rust."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Annotated

import typer

from crf_endereco.config import CAMINHO_DATASET, CAMINHO_TAGGER
from crf_endereco.features import ExtratorFeature
from crf_endereco.modelos.inferencia import carregar_tagger, segmentar
from crf_endereco.segmentador_rust import rodar_segmentacao


def printa_segmentos(segmentos: list[dict[str, str]]) -> None:
    for segmento in segmentos:
        print(f"  {segmento['tipo']:<20} {segmento['valor']}")


def diferencial(
    dataset: Annotated[
        Path, typer.Argument(help="banco de anotacao")
    ] = CAMINHO_DATASET,
    tagger: Annotated[Path, typer.Option(help="tagger treinado")] = CAMINHO_TAGGER,
) -> None:
    """Compara a segmentacao do CRF em Python e no binario Rust.

    As duas versoes precisam usar o mesmo modelo, senao a comparacao mistura
    diferenca de features com diferenca de treino.
    """
    crf = carregar_tagger(tagger)
    extrator = ExtratorFeature()

    con = sqlite3.connect(str(dataset))
    enderecos = [
        str(linha[0]) for linha in con.execute("select endereco from enderecos")
    ]
    con.close()

    segmentos_python = [segmentar(crf, extrator, endereco) for endereco in enderecos]
    saida_rust = rodar_segmentacao(enderecos, modelo=tagger)

    diferentes = 0
    for endereco, bruto, segmentos in zip(
        enderecos, saida_rust, segmentos_python, strict=True
    ):
        try:
            segmentos_rust = json.loads(bruto)
        except json.JSONDecodeError as erro:
            raise typer.BadParameter(
                f"o segmentador devolveu JSON invalido para {endereco!r}: {erro}"
            ) from erro
        if segmentos_rust == segmentos:
            continue
        diferentes += 1
        print("-------------")
        print(endereco, "\n")
        print("[Python]")
        printa_segmentos(segmentos)
        print("\n[Rust]")
        printa_segmentos(segmentos_rust)

    print("------")
    print(f"Total Casos Diferentes: {diferentes}/{len(enderecos)}")
