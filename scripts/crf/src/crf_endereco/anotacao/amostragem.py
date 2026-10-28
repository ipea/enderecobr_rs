"""Coleta de um lote balanceado entre UF e origem."""

from __future__ import annotations

import random
import sqlite3
from collections.abc import Sequence

from crf_endereco.anotacao import consultas
from crf_endereco.anotacao.estratificacao import (
    EstratoPendente,
    LinhaPendente,
    alocar,
)


def coletar_lote_balanceado(
    conn: sqlite3.Connection,
    *,
    limite: int | None,
    lote: str | None,
    incluir_erros: bool,
    ufs: Sequence[str] | None = None,
    origens: Sequence[str] | None = None,
    municipios: Sequence[str] | None = None,
    usar_filtro_crf: bool = False,
) -> tuple[list[LinhaPendente], list[tuple[EstratoPendente, EstratoPendente, int]]]:
    """Coleta um lote com cotas hierárquicas UF → origem, pesando 1/(anotados+1).

    Sem `limite`, usa o total de pendentes (equivale a pegar tudo). Primeiro
    distribui o lote entre as UFs; depois, dentro da cota de cada UF, distribui
    entre as origens dela. As linhas de cada origem saem em ordem aleatória e o
    lote final é embaralhado. Retorna também a alocação por (UF, origem) para o
    relatório. `ufs`/`origens`/`municipios` restringem os estratos considerados;
    `usar_filtro_crf` restringe todo o processo aos ids aprovados pelo modelo.
    """
    estratos_uf = consultas.listar_ufs_pendentes(
        conn,
        lote=lote,
        incluir_erros=incluir_erros,
        ufs=ufs,
        municipios=municipios,
        usar_filtro_crf=usar_filtro_crf,
    )
    tamanho = limite if limite is not None else sum(u.pendentes for u in estratos_uf)

    linhas: list[LinhaPendente] = []
    alocacao: list[tuple[EstratoPendente, EstratoPendente, int]] = []
    for uf, cota_uf in alocar(estratos_uf, tamanho):
        estratos_origem = consultas.listar_origens_pendentes(
            conn,
            uf.chave,
            lote=lote,
            incluir_erros=incluir_erros,
            origens=origens,
            municipios=municipios,
            usar_filtro_crf=usar_filtro_crf,
        )
        for origem, cota_origem in alocar(estratos_origem, cota_uf):
            linhas.extend(
                consultas.selecionar_pendentes(
                    conn,
                    limite=cota_origem,
                    lote=lote,
                    incluir_erros=incluir_erros,
                    origens=[origem.chave],
                    ufs=[uf.chave],
                    municipios=municipios,
                    usar_filtro_crf=usar_filtro_crf,
                )
            )
            alocacao.append((uf, origem, cota_origem))
    random.shuffle(linhas)
    return linhas, alocacao
