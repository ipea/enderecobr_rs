"""Pendentes do dataset: recorte e sorteio balanceado entre as origens."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Pendente:
    """Uma linha ainda nao processada do dataset de etiquetagem."""

    id: int
    endereco: str
    extras: str


@dataclass(frozen=True)
class Filtros:
    """Recorte do dataset de etiquetagem."""

    lote: str | None = None
    incluir_erros: bool = False
    ufs: Sequence[str] = ()
    origens: Sequence[str] = ()
    municipios: Sequence[str] = ()
    # Ids aprovados pelo filtro do CRF; `None` desliga o filtro.
    ids: frozenset[int] | None = None

    def parametros(self) -> dict[str, Any]:
        """Parametros nomeados: listas viram JSON e o SQL usa `json_each`."""

        def lista(valores: Sequence[str] | None) -> str | None:
            itens = [item.strip() for item in valores or () if item.strip()]
            return json.dumps(itens) if itens else None

        return {
            "lote": self.lote,
            "incluir_erros": self.incluir_erros,
            "ufs": lista(self.ufs),
            "origens": lista(self.origens),
            "municipios": lista(self.municipios),
            "ids": json.dumps(sorted(self.ids)) if self.ids is not None else None,
        }


# Pendentes em ordem de sorteio, balanceada entre as celulas (UF, origem) e
# pesando 1/(anotados+1) da celula:
#
# - `rodada` e a posicao da linha dentro da sua celula. Ordenar por ela faz um
#   round-robin: a primeira linha de cada celula, depois a segunda de cada uma
#   e assim por diante - nenhuma origem grande domina o lote.
# - dentro da rodada, a celula com menos anotacoes vem primeiro (peso 1/(n+1)),
#   que e o que empurra o lote para o que ainda nao foi coberto.
SQL_PENDENTES = """
WITH anotados AS (
    SELECT coalesce(uf, '') AS uf, origem, count(*) AS n
    FROM enderecos
    WHERE resposta_llm IS NOT NULL
      AND json_extract(resposta_llm, '$.erro') IS NULL
    GROUP BY 1, 2
),
pend AS (
    SELECT id, endereco, extras, coalesce(uf, '') AS uf, origem
    FROM enderecos
    WHERE (
            resposta_llm IS NULL
            OR (:incluir_erros AND json_extract(resposta_llm, '$.erro') IS NOT NULL)
          )
      AND (:lote IS NULL OR lote = :lote)
      AND (
            :ufs IS NULL
            OR upper(coalesce(uf, '')) IN (SELECT upper(value) FROM json_each(:ufs))
          )
      AND (
            :origens IS NULL
            OR lower(origem) IN (SELECT lower(value) FROM json_each(:origens))
          )
      AND (
            :municipios IS NULL
            OR upper(coalesce(municipio, ''))
               IN (SELECT upper(value) FROM json_each(:municipios))
          )
      AND (:ids IS NULL OR id IN (SELECT value FROM json_each(:ids)))
)
SELECT id, endereco, extras
FROM (
    SELECT pend.*,
           coalesce(anotados.n, 0) AS anotados_celula,
           row_number() OVER (
               PARTITION BY pend.uf, pend.origem ORDER BY random()
           ) AS rodada
    FROM pend
    LEFT JOIN anotados
           ON anotados.uf = pend.uf AND anotados.origem = pend.origem
)
ORDER BY rodada, anotados_celula, random()
LIMIT coalesce(:limite, -1)
"""


def pendentes(
    conn: sqlite3.Connection, filtros: Filtros, limite: int | None = None
) -> list[Pendente]:
    """Pendentes do recorte, em ordem de sorteio (todos quando `limite` e nulo)."""
    linhas = conn.execute(
        SQL_PENDENTES, {**filtros.parametros(), "limite": limite}
    ).fetchall()
    return [
        Pendente(
            id=int(linha["id"]),
            endereco=str(linha["endereco"]),
            extras=str(linha["extras"]),
        )
        for linha in linhas
    ]


def contar(conn: sqlite3.Connection, filtros: Filtros) -> int:
    """Quantos pendentes o recorte tem (sem sortear)."""
    return len(pendentes(conn, filtros))
