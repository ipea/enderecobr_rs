"""Pendentes do dataset: recorte e sorteio balanceado entre as origens."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from crf_endereco.features.texto import normalize


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
    # Só linhas com `$.erro`: retry da fila sem varrer os nunca-anotados.
    apenas_erros: bool = False
    ufs: Sequence[str] = ()
    origens: Sequence[str] = ()
    municipios: Sequence[str] = ()
    # Trecho do endereco (busca ignorando caixa e acentos); vazio desliga.
    busca: str | None = None
    # Ids aprovados pelo filtro do CRF; `None` desliga o filtro.
    ids: frozenset[int] | None = None

    def parametros(self) -> dict[str, Any]:
        """Parametros nomeados: listas viram JSON e o SQL usa `json_each`."""

        def lista(valores: Sequence[str] | None) -> str | None:
            itens = [item.strip() for item in valores or () if item.strip()]
            return json.dumps(itens) if itens else None

        busca = (self.busca or "").strip()
        return {
            "lote": self.lote,
            "incluir_erros": self.incluir_erros,
            "apenas_erros": self.apenas_erros,
            "ufs": lista(self.ufs),
            "origens": lista(self.origens),
            "municipios": lista(self.municipios),
            "busca": padrao_busca(busca) if busca else None,
            "ids": json.dumps(sorted(self.ids)) if self.ids is not None else None,
        }


def sem_acento(texto: str) -> str:
    """Texto em ASCII e caixa alta, para comparar ignorando acento e caixa."""
    return normalize(texto).upper()


def padrao_busca(busca: str) -> str:
    """Padrao `LIKE` do trecho, com `%` e `_` tratados como literais."""
    # Espacos repetidos ou nas pontas nao fazem parte do trecho buscado.
    trecho = " ".join(sem_acento(busca).split())
    escapado = trecho.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escapado}%"


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
            (
                :apenas_erros
                AND json_extract(resposta_llm, '$.erro') IS NOT NULL
            )
            OR (
                NOT :apenas_erros
                AND (
                    resposta_llm IS NULL
                    OR (
                        :incluir_erros
                        AND json_extract(resposta_llm, '$.erro') IS NOT NULL
                    )
                )
            )
          )
      AND (:lote IS NULL OR lote = :lote)
      AND (:busca IS NULL OR sem_acento(endereco) LIKE :busca ESCAPE '\\')
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
    # `--busca` compara textos normalizados; a funcao so existe nesta conexao.
    conn.create_function("sem_acento", 1, sem_acento, deterministic=True)
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
