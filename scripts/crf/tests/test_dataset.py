import json
import sqlite3

import pytest

from crf_endereco.anotacao.lote import gravar_gravacoes
from crf_endereco.dataset import (
    carregar_detalhes,
    criar_banco,
    gravar_resposta,
    serializar_erro,
)

RESPOSTA_ANTIGA = (
    '{"segmentos": [{"tipo": "logradouro", "valor": "RUA A"}], "comentario": null}'
)
RESPOSTA_NOVA = (
    '{"segmentos": [{"tipo": "localidade", "valor": "RUA A"}], "comentario": null}'
)


def banco_com_uma_linha() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    criar_banco(conn)
    _ = conn.execute(
        """
        INSERT INTO enderecos
            (id, endereco, origem, lote, hash_endereco, data_criacao, llm,
             resposta_llm, data_processamento)
        VALUES (1, 'RUA A', 'origem', 'lote', 'h1', '2026-01-01', 'llm-antiga',
                ?, '2026-01-02')
        """,
        (RESPOSTA_ANTIGA,),
    )
    conn.commit()
    return conn


def test_gravar_resposta_simples_nao_mexe_no_meta() -> None:
    conn = banco_com_uma_linha()

    gravar_resposta(conn, 1, RESPOSTA_NOVA, "llm-nova")

    linha = conn.execute("SELECT meta, resposta_llm FROM enderecos").fetchone()
    assert json.loads(linha["meta"]) == {}
    assert linha["resposta_llm"] == RESPOSTA_NOVA


def test_gravar_resposta_revisada_empilha_a_resposta_anterior() -> None:
    conn = banco_com_uma_linha()

    gravar_resposta(conn, 1, RESPOSTA_NOVA, "llm-nova", revisado_por="tagger_v13")

    linha = conn.execute("SELECT meta, resposta_llm FROM enderecos").fetchone()
    meta = json.loads(linha["meta"])
    assert meta["revisado"]["modelo"] == "tagger_v13"
    # a resposta trocada, com quem a produziu e quando: sem isso a revisao
    # apagaria o rotulo que treinou o modelo sem deixar rastro
    assert meta["revisoes"] == [
        {
            "data": "2026-01-02",
            "llm": "llm-antiga",
            "resposta": json.loads(RESPOSTA_ANTIGA),
        }
    ]
    assert linha["resposta_llm"] == RESPOSTA_NOVA


def test_gravar_resposta_revisada_de_novo_acrescenta_ao_historico() -> None:
    conn = banco_com_uma_linha()

    gravar_resposta(conn, 1, RESPOSTA_NOVA, "llm-nova", revisado_por="tagger_v13")
    gravar_resposta(conn, 1, RESPOSTA_ANTIGA, "llm-nova", revisado_por="tagger_v13")

    meta = json.loads(conn.execute("SELECT meta FROM enderecos").fetchone()["meta"])
    assert [revisao["resposta"] for revisao in meta["revisoes"]] == [
        json.loads(RESPOSTA_ANTIGA),
        json.loads(RESPOSTA_NOVA),
    ]


def test_revisao_nao_grava_a_linha_que_falhou() -> None:
    conn = banco_com_uma_linha()
    _ = conn.execute(
        """
        INSERT INTO enderecos
            (id, endereco, origem, lote, hash_endereco, data_criacao, resposta_llm)
        VALUES (2, 'RUA B', 'origem', 'lote', 'h2', '2026-01-01', ?)
        """,
        (RESPOSTA_ANTIGA,),
    )
    conn.commit()

    sucessos, erros = gravar_gravacoes(
        conn,
        [(1, RESPOSTA_NOVA, True), (2, serializar_erro("falhou"), False)],
        "llm-nova",
        revisado_por="tagger_v13",
    )

    assert (sucessos, erros) == (1, 1)
    linhas = {
        linha["id"]: linha["resposta_llm"]
        for linha in conn.execute("SELECT id, resposta_llm FROM enderecos")
    }
    assert linhas[1] == RESPOSTA_NOVA
    # o rotulo que ja existia nao pode virar um `{"erro": ...}`
    assert linhas[2] == RESPOSTA_ANTIGA


# --- detalhes para o `explorar` --------------------------------------------


def banco_com_revisao() -> sqlite3.Connection:
    """Uma linha revisada: alvo atual em `resposta_llm`, anterior em `meta`."""
    conn = banco_com_uma_linha()
    _ = conn.execute(
        """
        UPDATE enderecos
        SET meta = json_object(
                'revisado', json_object('modelo', 'tagger_v13'),
                'revisoes', json_array(
                    json_object('llm', 'llm-antiga', 'resposta', json(?))
                )
            ),
            recorte = 'tagger_v13/treino', uf = 'DF', municipio = 'BRASILIA'
        WHERE id = 1
        """,
        (RESPOSTA_ANTIGA,),
    )
    conn.commit()
    return conn


def test_carregar_detalhes_decodifica_resposta_e_historico() -> None:
    detalhe = carregar_detalhes(banco_com_revisao(), [1])[1]

    assert detalhe.endereco == "RUA A"
    assert detalhe.recorte == "tagger_v13/treino"
    assert detalhe.llm == "llm-antiga"
    assert detalhe.segmentos == ({"tipo": "logradouro", "valor": "RUA A"},)
    assert detalhe.erro is None
    assert detalhe.revisado_por == "tagger_v13"
    assert detalhe.revisoes[0]["resposta"]["segmentos"][0]["tipo"] == "logradouro"


def test_carregar_detalhes_sem_ids_nao_consulta() -> None:
    assert carregar_detalhes(banco_com_uma_linha(), []) == {}


def test_carregar_detalhes_de_linha_nunca_etiquetada_nao_tem_alvo() -> None:
    conn = banco_com_uma_linha()
    _ = conn.execute("UPDATE enderecos SET resposta_llm = NULL WHERE id = 1")
    conn.commit()

    detalhe = carregar_detalhes(conn, [1])[1]

    assert detalhe.segmentos == ()
    assert detalhe.revisoes == ()


def test_carregar_detalhes_recusa_resposta_invalida() -> None:
    conn = banco_com_uma_linha()
    _ = conn.execute("UPDATE enderecos SET resposta_llm = '{nao json' WHERE id = 1")
    conn.commit()

    with pytest.raises(RuntimeError):
        _ = carregar_detalhes(conn, [1])
