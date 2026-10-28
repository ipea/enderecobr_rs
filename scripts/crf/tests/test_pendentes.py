import json
import sqlite3
from collections import Counter

from crf_endereco.anotacao.pendentes import Filtros, contar, pendentes
from crf_endereco.dataset import criar_banco

Celula = tuple[str, str]


def banco_com(
    linhas: list[tuple[str, str, int]], municipio: str = "MUNICIPIO"
) -> tuple[sqlite3.Connection, dict[int, Celula]]:
    """Banco em memoria com `linhas` = (origem, uf, n_pendentes).

    Devolve tambem o mapa `id -> (origem, uf)`, para as assercoes falarem de
    celulas em vez de numeros magicos.
    """
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    criar_banco(conn)
    celulas: dict[int, Celula] = {}
    identificador = 0
    for origem, uf, quantidade in linhas:
        for _ in range(quantidade):
            identificador += 1
            celulas[identificador] = (origem, uf)
            _ = conn.execute(
                """
                INSERT INTO enderecos
                    (id, endereco, extras, meta, origem, uf, municipio, lote,
                     hash_endereco, data_criacao)
                VALUES (?, ?, '', '{}', ?, ?, ?, 'lote', ?, '2026-01-01')
                """,
                (
                    identificador,
                    f"R {identificador}",
                    origem,
                    uf,
                    municipio,
                    f"h{identificador}",
                ),
            )
    conn.commit()
    return conn, celulas


def marcar(conn: sqlite3.Connection, ids: set[int], resposta: str) -> None:
    for identificador in ids:
        _ = conn.execute(
            "UPDATE enderecos SET resposta_llm = ? WHERE id = ?",
            (resposta, identificador),
        )
    conn.commit()


def anotar(conn: sqlite3.Connection, ids: set[int]) -> None:
    marcar(conn, ids, json.dumps({"segmentos": []}))


def com_erro(conn: sqlite3.Connection, ids: set[int]) -> None:
    marcar(conn, ids, json.dumps({"erro": "falhou"}))


# --- recorte ---------------------------------------------------------------


def test_sem_limite_pega_todos_os_pendentes():
    conn, _ = banco_com([("A", "SP", 4), ("B", "MG", 6)])
    assert len(pendentes(conn, Filtros())) == 10
    assert contar(conn, Filtros()) == 10


def test_limite_corta_o_lote():
    conn, _ = banco_com([("A", "SP", 10)])
    assert len(pendentes(conn, Filtros(), 3)) == 3


def test_linha_ja_anotada_nao_esta_pendente():
    conn, _ = banco_com([("A", "SP", 3)])
    anotar(conn, {2})
    assert {linha.id for linha in pendentes(conn, Filtros())} == {1, 3}


def test_linha_com_erro_so_entra_com_incluir_erros():
    conn, _ = banco_com([("A", "SP", 3)])
    com_erro(conn, {2})
    assert {linha.id for linha in pendentes(conn, Filtros())} == {1, 3}
    com_erros = pendentes(conn, Filtros(incluir_erros=True))
    assert {linha.id for linha in com_erros} == {1, 2, 3}


def test_recorte_por_uf_origem_e_lote():
    conn, _ = banco_com([("A", "SP", 2), ("B", "SP", 2), ("A", "RJ", 2)])
    assert {linha.id for linha in pendentes(conn, Filtros(ufs=["sp"]))} == {1, 2, 3, 4}
    assert {linha.id for linha in pendentes(conn, Filtros(origens=["B"]))} == {3, 4}
    assert pendentes(conn, Filtros(lote="nao-existe")) == []


def test_recorte_por_municipio():
    conn, _ = banco_com([("A", "SP", 2)], municipio="SAO PAULO")
    assert len(pendentes(conn, Filtros(municipios=["sao paulo"]))) == 2
    assert pendentes(conn, Filtros(municipios=["campinas"])) == []


def test_filtro_de_ids_limita_a_selecao():
    conn, _ = banco_com([("A", "SP", 4)])
    selecionados = pendentes(conn, Filtros(ids=frozenset({2, 4})))
    assert {linha.id for linha in selecionados} == {2, 4}


# --- balanceamento ---------------------------------------------------------


def test_round_robin_alterna_celulas_antes_de_repetir():
    # Uma origem grande (100) e uma pequena (3): o lote de 6 traz 3 de cada.
    conn, celulas = banco_com([("A", "SP", 100), ("B", "RJ", 3)])
    contagem = Counter(celulas[linha.id] for linha in pendentes(conn, Filtros(), 6))
    assert contagem[("A", "SP")] == 3
    assert contagem[("B", "RJ")] == 3


def test_celula_menos_anotada_vem_primeiro():
    # SP/A ja tem 3 anotados; RJ/B nenhum -> o primeiro sorteado e do RJ.
    conn, celulas = banco_com([("A", "SP", 8), ("B", "RJ", 8)])
    anotar(conn, {1, 2, 3})
    primeira = pendentes(conn, Filtros(), 1)[0]
    assert celulas[primeira.id] == ("B", "RJ")


def test_todas_as_celulas_aparecem_antes_de_esgotar_o_lote():
    conn, celulas = banco_com([("A", "SP", 50), ("B", "RJ", 50), ("C", "MG", 50)])
    escolhidas = {celulas[linha.id] for linha in pendentes(conn, Filtros(), 3)}
    assert escolhidas == {("A", "SP"), ("B", "RJ"), ("C", "MG")}
