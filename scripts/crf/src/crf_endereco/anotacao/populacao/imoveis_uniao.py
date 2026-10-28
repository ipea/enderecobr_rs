"""Base: imoveis da Uniao (SPU)."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

import duckdb

from crf_endereco.anotacao.populacao.populador import Fonte
from crf_endereco.registro import Registro, decimal, montar_extras, registro, texto

TIPO = "imoveis_uniao"
ROTULO = "Imóveis da União (SPU)"

# Planilha: o endereco ja vem concatenado e com geo.
CONSULTA = """
    SELECT "Rip Imóvel", "UF", "Município", "Bairro", "Endereço",
           "Latitude", "Longitude", "Nível de Precisão"
    FROM read_xlsx(?, sheet = ?)
    WHERE "Endereço" IS NOT NULL AND trim("Endereço") <> ''
"""


def preparar(conn: duckdb.DuckDBPyConnection) -> None:
    """A extensao `excel` e necessaria para ler o `.xlsx`."""
    _ = conn.execute("INSTALL excel; LOAD excel;")


def parametros(arquivo: Path, aba: str | None) -> list[Any]:
    return [str(arquivo), aba or "Sheet1"]


def registrar(linha: Sequence[Any], arquivo: Path, aba: str | None) -> Registro:
    rip, uf, municipio, bairro, endereco, lat, lon, precisao = linha
    return registro(
        endereco=endereco,
        extras=montar_extras(texto(municipio), texto(uf), texto(bairro), banco=ROTULO),
        meta={
            "latitude": decimal(lat),
            "longitude": decimal(lon),
            "nivel_precisao": precisao,
            "arquivo": str(arquivo),
            "aba": aba or "Sheet1",
        },
        origem=TIPO,
        origem_id=rip,
        municipio=municipio,
        uf=uf,
    )


FONTE = Fonte(
    tipo=TIPO,
    rotulo=ROTULO,
    consulta=CONSULTA,
    registrar=registrar,
    parametros=parametros,
    preparar=preparar,
)
