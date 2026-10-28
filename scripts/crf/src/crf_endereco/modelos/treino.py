"""Dados de treino: do SQLite anotado para features e rotulos do CRF."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from crf_endereco.config import CAMINHO_DATASET
from crf_endereco.dataset import carregar_anotados, segmentos_de
from crf_endereco.features import ExtratorFeature, tokenize
from crf_endereco.rotulos import mergear


@dataclass(frozen=True)
class Exemplos:
    """Dataset pronto para o CRF: features, rotulos, tokens e categorias."""

    x: list[list[dict[str, float]]]
    y: list[list[str]]
    tokens: list[list[str]]
    categorias: list[list[str]]


def carregar_exemplos(caminho: Path = CAMINHO_DATASET) -> Exemplos:
    """Le o dataset etiquetado e monta features/rotulos.

    E o unico caminho de dados do modelo: treino, busca de hiperparametros e
    avaliacao usam exatamente as mesmas linhas, features e etiquetas.
    """
    extrator = ExtratorFeature()
    x: list[list[dict[str, float]]] = []
    y: list[list[str]] = []
    tokens: list[list[str]] = []
    categorias: list[list[str]] = []

    print("Preprocessando dados...")
    for exemplo in carregar_anotados(caminho):
        toks, labels = mergear(exemplo.endereco, segmentos_de(exemplo), tokenize)
        x.append(extrator.tokens2features(toks))
        y.append(labels)
        tokens.append(toks)
        categorias.append([exemplo.origem, exemplo.uf])

    return Exemplos(x=x, y=y, tokens=tokens, categorias=categorias)
