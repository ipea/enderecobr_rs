"""Nomes de municípios conhecidos (`municipios.csv`), separados por ambiguidade."""

from __future__ import annotations

import csv
from collections.abc import Iterable
from functools import lru_cache
from pathlib import Path

from crf_endereco.config import AMBIGUIDADE_MUNICIPIOS, MUNICIPIOS
from crf_endereco.features.texto import normalize, tokenize

# Acima de tantos municípios usando o nome como localidade, o nome deixa de ser
# evidência de município: `BOA VISTA` (1492) é nome de bairro em qualquer lugar,
# `ANAPOLIS` (2) não. O limiar veio da curva de cobertura x falso-positivo no
# dataset anotado (60% dos spans de município cobertos com ~1% de erro).
LIMIAR_AMBIGUIDADE = 5


def chave_nome(nome: str) -> tuple[str, ...]:
    """Palavras do nome normalizadas e sem pontuação.

    `OLHO D'ÁGUA` vira `("OLHO", "D", "AGUA")`, a mesma chave que os tokens
    `OLHO`, `D`, `'`, `AGUA` do texto geram na comparação.
    """
    return tuple(
        tok for tok in (normalize(t).upper() for t in tokenize(nome)) if tok.isalnum()
    )


@lru_cache(maxsize=4)
def ler_nomes(caminho: Path = MUNICIPIOS) -> tuple[str, ...]:
    """Nomes de município do CSV, na ordem do arquivo."""
    with caminho.open(newline="", encoding="utf-8") as arquivo:
        return tuple(linha["municipio"] or "" for linha in csv.DictReader(arquivo))


@lru_cache(maxsize=4)
def carregar_ambiguidade(caminho: Path = AMBIGUIDADE_MUNICIPIOS) -> dict[str, int]:
    """Quantos municípios têm uma localidade com cada nome (0 = inequívoco).

    Sem o arquivo derivado todo nome fica inequívoco, que é o comportamento
    anterior à feature.
    """
    if not caminho.exists():
        return {}
    contagem: dict[str, int] = {}
    with caminho.open(newline="", encoding="utf-8") as arquivo:
        for linha in csv.DictReader(arquivo):
            chave = " ".join(chave_nome(linha["municipio"] or ""))
            if chave:
                contagem[chave] = max(contagem.get(chave, 0), int(linha["n_localidades"]))
    return contagem


def dividir_por_ambiguidade(
    nomes: Iterable[str],
    ambiguidade: dict[str, int],
    limiar: int = LIMIAR_AMBIGUIDADE,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Separa os nomes em inequívocos e ambíguos pelo uso como localidade."""
    unicos: list[str] = []
    ambiguos: list[str] = []
    for nome in nomes:
        n_localidades = ambiguidade.get(" ".join(chave_nome(nome)))
        if n_localidades is not None and n_localidades > limiar:
            ambiguos.append(nome)
        else:
            unicos.append(nome)
    return tuple(unicos), tuple(ambiguos)
