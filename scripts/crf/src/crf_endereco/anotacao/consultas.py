"""Consultas de pendentes no dataset (SQLite)."""
from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from typing import cast

from crf_endereco.anotacao.estratificacao import (
    EstratoPendente,
    LinhaPendente,
)
from crf_endereco.anotacao.filtro_crf import garantir_tabela_filtro


def _lista_delimitada(valores: Sequence[str] | None, *, caixa: str) -> str | None:
    """Junta um filtro em ``",v1,v2,"`` para uso com ``instr`` (ou ``None``).

    Mantém a consulta SQL estática (só o valor delimitado vai como parâmetro);
    o ``instr`` casa esse texto com a coluna já normalizada na base. ``caixa``
    é ``'upper'`` ou ``'lower'``. Sem valores, devolve ``None`` (filtro off).
    """
    if not valores:
        return None
    itens = [item.strip() for item in valores if item.strip()]
    if not itens:
        return None
    if caixa == "upper":
        itens = [item.upper() for item in itens]
    elif caixa == "lower":
        itens = [item.lower() for item in itens]
    return "," + ",".join(itens) + ","

def listar_ufs_pendentes(
    conn: sqlite3.Connection,
    *,
    lote: str | None = None,
    incluir_erros: bool = False,
    ufs: Sequence[str] | None = None,
    municipios: Sequence[str] | None = None,
    usar_filtro_crf: bool = False,
) -> list[EstratoPendente]:
    """UFs que têm pendentes, com quantos já foram anotados em cada uma.

    `anotados` conta só as anotações bem-sucedidas (sem `$.erro`); é a base do
    peso usado por `alocar` no primeiro nível (UF). UFs nulas viram a chave ''.
    `ufs`/`municipios` restringem os estratos (sem diferenciar maiúsc./minúsc.).
    `usar_filtro_crf` restringe aos ids aprovados pelo filtro do modelo.
    """
    garantir_tabela_filtro(conn)
    linhas = conn.execute(
        """
        SELECT coalesce(p.uf, '') AS uf,
               (SELECT count(*) FROM enderecos e
                 WHERE coalesce(e.uf, '') = coalesce(p.uf, '')
                   AND e.resposta_llm IS NOT NULL
                   AND json_extract(e.resposta_llm, '$.erro') IS NULL) AS anotados,
               count(*) AS pendentes
        FROM enderecos AS p
        WHERE (
                p.resposta_llm IS NULL
                OR (:incluir_erros AND json_extract(p.resposta_llm, '$.erro') IS NOT NULL)
              )
          AND (:lote IS NULL OR p.lote = :lote)
          AND (:ufs IS NULL OR instr(:ufs, ',' || upper(coalesce(p.uf, '')) || ',') > 0)
          AND (:municipios IS NULL OR instr(upper(:municipios), ',' || upper(coalesce(p.municipio, '')) || ',') > 0)
          AND (:usar_filtro_crf = 0 OR p.id IN (SELECT id FROM _filtro_crf))
        GROUP BY coalesce(p.uf, '')
        """,
        {
            "incluir_erros": incluir_erros,
            "lote": lote,
            "ufs": _lista_delimitada(ufs, caixa="upper"),
            "municipios": _lista_delimitada(municipios, caixa="upper"),
            "usar_filtro_crf": usar_filtro_crf,
        },
    ).fetchall()
    return [
        EstratoPendente(chave=cast(str, u), anotados=cast(int, a), pendentes=cast(int, p))
        for u, a, p in linhas
    ]

def listar_origens_pendentes(
    conn: sqlite3.Connection,
    uf: str,
    *,
    lote: str | None = None,
    incluir_erros: bool = False,
    origens: Sequence[str] | None = None,
    municipios: Sequence[str] | None = None,
    usar_filtro_crf: bool = False,
) -> list[EstratoPendente]:
    """Origens com pendentes dentro de uma UF, com quantos já foram anotados.

    Espelha `listar_ufs_pendentes` no segundo nível (origem dentro da UF); é a
    base do peso 1/(anotados da célula origem×UF + 1). `origens`/`municipios`
    restringem os estratos (sem diferenciar maiúsc./minúsc.).
    """
    garantir_tabela_filtro(conn)
    linhas = conn.execute(
        """
        SELECT p.origem,
               (SELECT count(*) FROM enderecos e
                 WHERE e.origem = p.origem
                   AND coalesce(e.uf, '') = coalesce(p.uf, '')
                   AND e.resposta_llm IS NOT NULL
                   AND json_extract(e.resposta_llm, '$.erro') IS NULL) AS anotados,
               count(*) AS pendentes
        FROM enderecos AS p
        WHERE coalesce(p.uf, '') = :uf
          AND (
                p.resposta_llm IS NULL
                OR (:incluir_erros AND json_extract(p.resposta_llm, '$.erro') IS NOT NULL)
              )
          AND (:lote IS NULL OR p.lote = :lote)
          AND (:origens IS NULL OR instr(:origens, ',' || lower(p.origem) || ',') > 0)
          AND (:municipios IS NULL OR instr(upper(:municipios), ',' || upper(coalesce(p.municipio, '')) || ',') > 0)
          AND (:usar_filtro_crf = 0 OR p.id IN (SELECT id FROM _filtro_crf))
        GROUP BY p.origem
        """,
        {
            "uf": uf,
            "incluir_erros": incluir_erros,
            "lote": lote,
            "origens": _lista_delimitada(origens, caixa="lower"),
            "municipios": _lista_delimitada(municipios, caixa="upper"),
            "usar_filtro_crf": usar_filtro_crf,
        },
    ).fetchall()
    return [
        EstratoPendente(chave=cast(str, o), anotados=cast(int, a), pendentes=cast(int, p))
        for o, a, p in linhas
    ]

def selecionar_pendentes(
    conn: sqlite3.Connection,
    *,
    limite: int | None = None,
    lote: str | None = None,
    incluir_erros: bool = False,
    origens: Sequence[str] | None = None,
    ufs: Sequence[str] | None = None,
    municipios: Sequence[str] | None = None,
    usar_filtro_crf: bool = False,
) -> list[LinhaPendente]:
    """Seleciona as linhas a processar: pendentes e, opcionalmente, com erro.

    Consulta com parâmetros nomeados: `incluir_erros` liga/desliga o ramo de
    erros; `limite` nulo vira `-1` (sem limite no SQLite); `lote` nulo desativa
    esse filtro; `origens`/`ufs`/`municipios` restringem por origem, UF e/ou
    município (listas, sem diferenciar maiúsc./minúsc.); `usar_filtro_crf`
    restringe aos ids aprovados pelo filtro do modelo.
    """
    garantir_tabela_filtro(conn)
    linhas = cast(
        list[sqlite3.Row],
        conn.execute(
            """
            SELECT id, endereco, extras FROM enderecos
            WHERE (
                resposta_llm IS NULL
                OR (:incluir_erros AND json_extract(resposta_llm, '$.erro') IS NOT NULL)
              )
              AND (:lote IS NULL OR lote = :lote)
              AND (:origens IS NULL OR instr(:origens, ',' || lower(origem) || ',') > 0)
              AND (:ufs IS NULL OR instr(:ufs, ',' || upper(coalesce(uf, '')) || ',') > 0)
              AND (:municipios IS NULL OR instr(upper(:municipios), ',' || upper(coalesce(municipio, '')) || ',') > 0)
              AND (:usar_filtro_crf = 0 OR id IN (SELECT id FROM _filtro_crf))
            ORDER BY random()
            LIMIT COALESCE(:limite, -1)
            """,
            {
                "incluir_erros": incluir_erros,
                "lote": lote,
                "limite": limite,
                "origens": _lista_delimitada(origens, caixa="lower"),
                "ufs": _lista_delimitada(ufs, caixa="upper"),
                "municipios": _lista_delimitada(municipios, caixa="upper"),
                "usar_filtro_crf": usar_filtro_crf,
            },
        ).fetchall(),
    )

    return [
        LinhaPendente(
            id=cast(int, linha["id"]),
            endereco=cast(str, linha["endereco"]),
            extras=cast(str, linha["extras"]),
        )
        for linha in linhas
    ]
