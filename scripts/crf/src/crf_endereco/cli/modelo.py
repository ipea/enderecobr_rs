"""Comandos do modelo: treinar, tunar, avaliar, segmentar, diferencial, inspecionar."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Annotated

import typer

from crf_endereco.config import CAMINHO_DATASET, CAMINHO_TAGGER
from crf_endereco.dataset import carregar_anotados
from crf_endereco.features import ExtratorFeature
from crf_endereco.modelo import crf as modelo_crf
from crf_endereco.modelo import relatorio
from crf_endereco.segmentador_rust import rodar_segmentacao

OpcaoDataset = Annotated[Path, typer.Option(help="banco de anotacao")]
OpcaoTagger = Annotated[Path, typer.Option(help="tagger treinado")]


def treinar(
    dataset: OpcaoDataset = CAMINHO_DATASET,
    saida: Annotated[Path, typer.Option(help="tagger a escrever")] = CAMINHO_TAGGER,
    fracao_teste: Annotated[
        float, typer.Option(help="fracao separada para teste")
    ] = 0.1,
) -> None:
    """Treina o CRF sobre o dataset anotado."""
    modelo_crf.treinar(dataset, saida, fracao_teste)


def tunar() -> None:
    """Busca hiperparametros do CRF."""
    modelo_crf.tunar()


def avaliar(
    dataset: OpcaoDataset = CAMINHO_DATASET, tagger: OpcaoTagger = CAMINHO_TAGGER
) -> None:
    """Avalia o CRF por token e por classe."""
    exemplos = modelo_crf.carregar_exemplos(dataset)
    relatorio.avaliar(
        exemplos.x, exemplos.y, exemplos.categorias, exemplos.tokens, tagger
    )


def segmentar(tagger: OpcaoTagger = CAMINHO_TAGGER) -> None:
    """Segmenta enderecos lidos do stdin."""
    crf = modelo_crf.carregar_tagger(tagger)
    extrator = ExtratorFeature()

    while True:
        try:
            linha = input()
        except EOFError:
            break
        if not linha:
            continue
        print("-----------------")
        for segmento in modelo_crf.segmentar(crf, extrator, linha):
            print(f"{segmento.get('tipo', '').title()}: {segmento.get('valor', '')}")


def diferencial(
    dataset: Annotated[
        Path, typer.Argument(help="banco de anotacao")
    ] = CAMINHO_DATASET,
    tagger: OpcaoTagger = CAMINHO_TAGGER,
) -> None:
    """Compara a segmentacao do CRF em Python e no binario Rust.

    As duas versoes precisam usar o mesmo modelo, senao a comparacao mistura
    diferenca de features com diferenca de treino.
    """
    crf = modelo_crf.carregar_tagger(tagger)
    extrator = ExtratorFeature()
    enderecos = [exemplo.endereco for exemplo in carregar_anotados(dataset)]

    segmentos_python = [
        modelo_crf.segmentar(crf, extrator, endereco) for endereco in enderecos
    ]
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
        _printa(segmentos)
        print("\n[Rust]")
        _printa(segmentos_rust)

    print("------")
    print(f"Total Casos Diferentes: {diferentes}/{len(enderecos)}")


def inspecionar(
    tagger: Annotated[Path, typer.Argument(help="Path do tagger treinado")] = (
        CAMINHO_TAGGER
    ),
    output: Annotated[
        Path | None, typer.Option("--output", "-o", help="Path do resultado")
    ] = None,
) -> None:
    """Lista os pesos aprendidos por atributo e rotulo."""
    crf = modelo_crf.carregar_tagger(tagger)
    linhas = [
        f"{weight:0.6f} {label:<8} {attr}\n"
        for (attr, label), weight in Counter(crf.state_features_).most_common()
    ]
    if output is None:
        print("".join(linhas), end="")
        return
    try:
        _ = output.write_text("".join(linhas), encoding="utf-8")
    except OSError as erro:
        raise typer.BadParameter(
            f"nao foi possivel escrever {output}: {erro}"
        ) from erro


def _printa(segmentos: list[dict[str, str]]) -> None:
    for segmento in segmentos:
        print(f"  {segmento['tipo']:<20} {segmento['valor']}")
