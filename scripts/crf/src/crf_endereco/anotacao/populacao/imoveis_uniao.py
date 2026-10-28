"""Populador dos imoveis da Uniao."""

from __future__ import annotations

from collections.abc import Iterator
from typing import ClassVar

import duckdb

from crf_endereco.anotacao.populacao.populador import Populador
from crf_endereco.registro import Registro, decimal, montar_extras, texto


class PopuladorImoveisUniao(Populador):
    """Imóveis da União (SPU): endereço já concatenado + geo.

    A consulta é um literal com placeholders (a extensão `excel` e o caminho
    entram como parâmetros, sem montar SQL com dados do usuário). A origem é
    percorrida em streaming, em lotes; a amostragem e o filtro acontecem
    depois, sobre o stream (ver `amostrar_reservatorio`).
    """

    tipo = "imoveis_uniao"
    rotulo = "Imóveis da União (SPU)"
    TAM_LOTE: ClassVar[int] = 20_000

    CONSULTA: ClassVar[str] = """
        SELECT "Rip Imóvel", "UF", "Município", "Bairro", "Endereço",
               "Latitude", "Longitude", "Nível de Precisão"
        FROM read_xlsx(?, sheet = ?)
        WHERE "Endereço" IS NOT NULL AND trim("Endereço") <> ''
    """

    def popular(
        self,
        conn: duckdb.DuckDBPyConnection,
    ) -> Iterator[Registro]:
        conn.execute("INSTALL excel; LOAD excel;")
        resultado = conn.execute(
            self.CONSULTA, [str(self.arquivo), self.aba or "Sheet1"]
        )

        while True:
            linhas = resultado.fetchmany(self.TAM_LOTE)
            if not linhas:
                break
            for linha in linhas:
                rip, uf, municipio, bairro, endereco, lat, lon, precisao = linha
                municipio = texto(municipio)
                uf = texto(uf)
                yield Registro(
                    endereco=str(endereco).strip(),
                    extras=montar_extras(
                        municipio, uf, bairro, banco="Imóveis da União"
                    ),
                    meta={
                        "latitude": decimal(lat),
                        "longitude": decimal(lon),
                        "nivel_precisao": precisao,
                        "arquivo": str(self.arquivo),
                        "aba": self.aba or "Sheet1",
                    },
                    origem=self.tipo,
                    origem_id=str(rip),
                    municipio=municipio,
                    uf=uf,
                )
