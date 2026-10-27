import sqlite3

import pytest

from crf_endereco.anotacao.amostragem import coletar_lote_balanceado
from crf_endereco.anotacao.consultas import (
    listar_origens_pendentes,
    listar_ufs_pendentes,
)
from crf_endereco.anotacao.estratificacao import EstratoPendente, alocar
from crf_endereco.anotacao.persistencia import criar_banco


def estrato(chave: str, anotados: int, pendentes: int) -> EstratoPendente:
    return EstratoPendente(chave=chave, anotados=anotados, pendentes=pendentes)


# --- alocar ---------------------------------------------------------------


def test_alocar_dividi_igualmente_quando_pesos_iguais():
    alocacao = alocar([estrato("A", 0, 100), estrato("B", 0, 100)], 10)
    assert {e.chave: q for e, q in alocacao} == {"A": 5, "B": 5}


def test_alocar_respeita_pendentes_e_repassa_excedente():
    # A satura com 1 pendente; o restante (9) vai todo para B.
    alocacao = alocar([estrato("A", 0, 1), estrato("B", 0, 100)], 10)
    assert {e.chave: q for e, q in alocacao} == {"A": 1, "B": 9}


def test_alocar_pondera_por_anotados():
    # Peso 1/(anotados+1): A (0 anotados) pesa 10x B (9 anotados).
    alocacao = {
        e.chave: q
        for e, q in alocar([estrato("A", 0, 1000), estrato("B", 9, 1000)], 100)
    }
    assert sum(alocacao.values()) == 100
    assert alocacao["A"] > alocacao["B"] * 5


def test_alocar_tamanho_zero_ou_sem_estratos():
    assert alocar([estrato("A", 0, 10)], 0) == []
    assert alocar([], 10) == []


def test_alocar_nunca_excede_o_total_quando_ha_capacidade():
    alocacao = alocar(
        [estrato("A", 0, 3), estrato("B", 0, 3), estrato("C", 0, 100)], 20
    )
    assert sum(q for _, q in alocacao) == 20


# --- integração com o banco ----------------------------------------------


def banco_com(linhas: list[tuple[str, str | None, int]]) -> sqlite3.Connection:
    """Cria um banco em memória com `linhas` = (origem, uf, n_pendentes)."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    criar_banco(conn)
    identificador = 0
    for origem, uf, quantidade in linhas:
        for _ in range(quantidade):
            identificador += 1
            _ = conn.execute(
                """
                INSERT INTO enderecos
                    (id, endereco, extras, meta, origem, uf, lote,
                     hash_endereco, data_criacao)
                VALUES (?, ?, '', '{}', ?, ?, 'lote', ?, '2026-01-01')
                """,
                (identificador, f"R {identificador}", origem, uf, f"h{identificador}"),
            )
    conn.commit()
    return conn


def test_listar_ufs_pendentes_conta_por_uf():
    conn = banco_com([("A", "SP", 2), ("A", "RJ", 3), ("B", "SP", 1)])
    ufs = listar_ufs_pendentes(conn)
    assert {e.chave: e.pendentes for e in ufs} == {"SP": 3, "RJ": 3}


def test_listar_origens_pendentes_conta_dentro_da_uf():
    conn = banco_com([("A", "SP", 2), ("B", "SP", 3), ("A", "RJ", 9)])
    origens = listar_origens_pendentes(conn, "SP")
    assert {e.chave: e.pendentes for e in origens} == {"A": 2, "B": 3}


def test_coletar_balanceia_uf_e_origem_hierarquicamente():
    # UFs equilibradas primeiro: SP, RJ e MG recebem cotas iguais; dentro de
    # cada UF, as origens dividem a cota.
    conn = banco_com([("A", "SP", 100), ("A", "RJ", 100), ("B", "MG", 100)])
    linhas, alocacao = coletar_lote_balanceado(
        conn, limite=30, lote=None, incluir_erros=False
    )

    assert len(linhas) == 30
    por_uf: dict[str, int] = {}
    for uf, _origem, quantidade in alocacao:
        por_uf[uf.chave] = por_uf.get(uf.chave, 0) + quantidade
    assert por_uf == {"SP": 10, "RJ": 10, "MG": 10}

    por_celula = {(u.chave, o.chave): q for u, o, q in alocacao}
    assert por_celula == {("SP", "A"): 10, ("RJ", "A"): 10, ("MG", "B"): 10}


def test_coletar_sem_limite_pega_todos_os_pendentes():
    conn = banco_com([("A", "SP", 4), ("B", "MG", 6)])
    linhas, _ = coletar_lote_balanceado(
        conn, limite=None, lote=None, incluir_erros=False
    )
    assert len(linhas) == 10


def test_coletar_respeita_uf_saturada():
    # UF SP tem só 1 pendente -> entrega o excedente para RJ.
    conn = banco_com([("A", "SP", 1), ("A", "RJ", 100)])
    linhas, alocacao = coletar_lote_balanceado(
        conn, limite=20, lote=None, incluir_erros=False
    )
    por_celula = {(u.chave, o.chave): q for u, o, q in alocacao}
    assert len(linhas) == 20
    assert por_celula == {("SP", "A"): 1, ("RJ", "A"): 19}


def test_coletar_respeita_origem_saturada_dentro_da_uf():
    # Na UF SP, a origem A tem só 1 pendente -> o excedente vai para B.
    conn = banco_com([("A", "SP", 1), ("B", "SP", 100)])
    linhas, alocacao = coletar_lote_balanceado(
        conn, limite=10, lote=None, incluir_erros=False
    )
    por_celula = {(u.chave, o.chave): q for u, o, q in alocacao}
    assert len(linhas) == 10
    assert por_celula == {("SP", "A"): 1, ("SP", "B"): 9}


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
