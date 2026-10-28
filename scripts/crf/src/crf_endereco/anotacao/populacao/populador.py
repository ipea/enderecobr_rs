"""Contrato dos populadores e utilidades comuns."""

from __future__ import annotations

import random
from abc import ABC, abstractmethod
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import ClassVar

import duckdb
from rapidfuzz import fuzz, process

from crf_endereco.config import MUNICIPIOS
from crf_endereco.registro import Registro


class FiltroDiversidade(ABC):
    """Decide se um endereço sorteado entra no dataset (para aumentar a diversidade)."""

    @abstractmethod
    def aceitar(self, endereco: str) -> bool:
        """True se `endereco` pode entrar no dataset (não fere a diversidade)."""


class SemFiltroDiversidade(FiltroDiversidade):
    """Aceita tudo — usado quando nenhum limiar de diversidade é informado."""

    def aceitar(self, endereco: str) -> bool:
        return True


class FiltroDiversidadeFuzzy(FiltroDiversidade):
    """Descarta sorteados parecidos demais com endereços já aceitos (rapidfuzz).

    Compara cada candidato com os endereços já presentes (baseline do banco +
    aceitos nesta rodada) e rejeita quando a similaridade alcança o limiar.
    `similaridade_maxima` e `distancia_minima` são complementares, na escala
    0–100 do rapidfuzz (`distancia = 100 - similaridade`).
    """

    def __init__(
        self,
        aceitos: Iterable[str] = (),
        *,
        similaridade_maxima: float | None = None,
    ) -> None:
        self.aceitos: list[str] = list(aceitos)
        self.limite = 0.0
        if similaridade_maxima is not None:
            self.limite = max(self.limite, similaridade_maxima)

    def aceitar(self, endereco: str) -> bool:
        # `score_cutoff` corta cedo: só interessa um match >= limite.
        if process.extractOne(
            endereco,
            self.aceitos,
            scorer=fuzz.token_sort_ratio,
            score_cutoff=self.limite,
        ):
            return False
        self.aceitos.append(endereco)
        return True


class Populador(ABC):
    """Lê uma origem e rende registros prontos para o dataset."""

    tipo: ClassVar[str]
    rotulo: ClassVar[str]

    def __init__(self, arquivo: Path, aba: str | None = None) -> None:
        self.arquivo = arquivo
        self.aba = aba

    @abstractmethod
    def popular(
        self,
        conn: duckdb.DuckDBPyConnection,
    ) -> Iterator[Registro]:
        """Percorre a origem em streaming, rendendo um registro por linha."""


def ultimo_campo(endereco: str) -> str:
    """Último campo do endereço (após a última vírgula) — candidato a bairro.

    Vazio quando o endereço não tem vírgula (linha de campo único).
    """
    partes = [parte.strip() for parte in endereco.split(",")]
    if len(partes) < 2:
        return ""
    return partes[-1]


def rng_registro(origem_id: str) -> random.Random:
    """RNG determinístico por entidade (a junção não muda entre execuções).

    `random.Random(str)` semeia via sha512 (independente de PYTHONHASHSEED),
    então a mesma entidade rende sempre a mesma junção.
    """
    return random.Random(origem_id)


def municipios_csv() -> Path | None:
    """`municipios.csv` (cod_ibge, municipio, uf) do repositorio, se existir.

    A ANEEL/CAFIR/SIASE/CadUnico so trazem o codigo IBGE; este arquivo (em
    `src/data/` do repositorio `enderecobr_rs`) resolve o nome e a UF.
    """
    return MUNICIPIOS if MUNICIPIOS.is_file() else None
