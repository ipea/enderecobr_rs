"""Populador do censo escolar (INEP)."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any, ClassVar

import duckdb

from crf_endereco.anotacao.populacao.populador import Populador
from crf_endereco.registro import Registro, decimal, montar_extras, texto


class PopuladorCensoEscolar(Populador):
    """Escolas do Censo Escolar (INEP): endereço concatenado + geo.

    A origem é o CSV detalhado do censo (uma linha por escola). O endereço já
    vem bruto, com CEP e 'Município - UF' ao fim, e é mantido como veio. O
    contexto da escola (município/UF, nome, dependência e localidade
    diferenciada) entra em `extras`, sem popular segmentos.
    """

    tipo = "censo_escolar"
    rotulo = "Censo Escolar (INEP)"
    TAM_LOTE: ClassVar[int] = 20_000

    # Valores de "Localidade Diferenciada" sem conteúdo útil (não viram extras).
    LOCALIDADE_DIFERENCIADA_IGNORAR: ClassVar[frozenset[str]] = frozenset(
        {
            "A escola não está em área de localização diferenciada",
            "Não Informado",
        }
    )

    CONSULTA: ClassVar[str] = """
        SELECT "Escola", "Código INEP", "UF", "Município",
               "Localidade Diferenciada", "Dependência Administrativa",
               "Endereço", "Latitude", "Longitude"
        FROM read_csv(?, header = true, all_varchar = true)
        WHERE "Endereço" IS NOT NULL AND trim("Endereço") <> ''
    """

    def popular(
        self,
        conn: duckdb.DuckDBPyConnection,
    ) -> Iterator[Registro]:
        resultado = conn.execute(self.CONSULTA, [str(self.arquivo)])

        while True:
            linhas = resultado.fetchmany(self.TAM_LOTE)
            if not linhas:
                break
            for linha in linhas:
                (
                    escola,
                    codigo_inep,
                    uf,
                    municipio,
                    localidade,
                    dependencia,
                    endereco,
                    lat,
                    lon,
                ) = linha
                escola = texto(escola)
                dependencia = texto(dependencia)
                localidade = self._limpar_localidade(localidade)
                municipio = texto(municipio)
                uf = texto(uf)
                yield Registro(
                    endereco=str(endereco).strip(),
                    extras=montar_extras(
                        municipio,
                        uf,
                        None,
                        banco="Censo Escolar (INEP)",
                        extras_adicionais=[
                            ("Escola", escola),
                            ("Dependência Administrativa", dependencia),
                            ("Localidade Diferenciada", localidade),
                        ],
                    ),
                    meta={
                        "latitude": decimal(lat),
                        "longitude": decimal(lon),
                        "escola": escola,
                        "dependencia_administrativa": dependencia,
                        "localidade_diferenciada": localidade or None,
                        "arquivo": str(self.arquivo),
                    },
                    origem=self.tipo,
                    origem_id=texto(codigo_inep) or None,
                    municipio=municipio,
                    uf=uf,
                )

    def _limpar_localidade(self, valor: Any) -> str:
        """Descarta marcadores sem conteúdo útil de localidade diferenciada."""
        bruto = texto(valor)
        if bruto.casefold() in {
            ignorar.casefold() for ignorar in self.LOCALIDADE_DIFERENCIADA_IGNORAR
        }:
            return ""
        return bruto
