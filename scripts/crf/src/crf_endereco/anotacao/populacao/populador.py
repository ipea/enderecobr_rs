"""Contrato das bases publicas: SQL, parametros e linha -> Registro.

Cada base e um dado (`Fonte`), nao uma classe: a leitura em streaming, o
preparo da conexao e a traducao da linha sao funcoes que a base fornece.
"""

from __future__ import annotations

import random
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import duckdb

from crf_endereco.config import MUNICIPIOS
from crf_endereco.registro import Registro

# Quantas linhas a consulta entrega por vez (a origem e lida em streaming).
TAM_LOTE = 20_000


def nada(_: duckdb.DuckDBPyConnection) -> None:
    """Bases que nao precisam preparar a conexao."""


def parametros_arquivo(arquivo: Path, _aba: str | None) -> list[Any]:
    """Consulta que recebe so o caminho (`*.parquet` quando for diretorio)."""
    return [str(arquivo / "*.parquet") if arquivo.is_dir() else str(arquivo)]


def parametros_municipios(arquivo: Path, _aba: str | None) -> list[Any]:
    """Consulta que junta o `municipios.csv` para resolver o codigo IBGE."""
    return [str(arquivo), str(municipios_csv())]


def municipios_csv() -> Path:
    """`municipios.csv` (cod_ibge, municipio, uf) do repositorio."""
    if not MUNICIPIOS.is_file():
        raise RuntimeError(
            f"municipios.csv (cod_ibge, municipio, uf) nao encontrado em {MUNICIPIOS}"
        )
    return MUNICIPIOS


@dataclass(frozen=True)
class Fonte:
    """Uma base publica: a consulta, seus parametros e o que fazer com a linha."""

    tipo: str
    rotulo: str
    consulta: str
    registrar: Callable[[Sequence[Any], Path, str | None], Registro]
    parametros: Callable[[Path, str | None], list[Any]] = parametros_arquivo
    preparar: Callable[[duckdb.DuckDBPyConnection], None] = nada


def ler(
    conn: duckdb.DuckDBPyConnection,
    fonte: Fonte,
    arquivo: Path,
    aba: str | None = None,
) -> Iterator[Registro]:
    """Percorre a origem em streaming, rendendo um registro por linha."""
    fonte.preparar(conn)
    resultado = conn.execute(fonte.consulta, fonte.parametros(arquivo, aba))
    while bloco := resultado.fetchmany(TAM_LOTE):
        for linha in bloco:
            yield fonte.registrar(linha, arquivo, aba)


def rng_registro(origem_id: str) -> random.Random:
    """RNG deterministico por entidade (a juncao nao muda entre execucoes).

    `random.Random(str)` semeia via sha512 (independente de PYTHONHASHSEED),
    entao a mesma entidade rende sempre a mesma juncao.
    """
    return random.Random(origem_id)


def ultimo_campo(endereco: str) -> str:
    """Ultimo campo do endereco (apos a ultima virgula) - candidato a bairro.

    Vazio quando o endereco nao tem virgula (linha de campo unico).
    """
    partes = [parte.strip() for parte in endereco.split(",")]
    return partes[-1] if len(partes) > 1 else ""
