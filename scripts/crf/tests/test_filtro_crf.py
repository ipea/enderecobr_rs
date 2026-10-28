import json
import sqlite3
from pathlib import Path

import pytest
from typer import BadParameter

from crf_endereco.anotacao.filtro_crf import (
    filtrar_ids_por_tipos,
    validar_tipos,
)
from crf_endereco.anotacao.pendentes import Filtros, pendentes
from crf_endereco.dataset import criar_banco
from crf_endereco.segmentador_rust import comando_segmentacao


def segmentacao(*tipos: str) -> str:
    """JSON de saída do segmentador, no formato de `padronizar segmentacao`."""
    return json.dumps(
        {
            "segmentos": [
                {"valor": f"v{i}", "tipo": tipo} for i, tipo in enumerate(tipos)
            ]
        }
    )


def banco_com(linhas: list[tuple[str, str, int]]) -> sqlite3.Connection:
    """Banco em memória com `linhas` = (origem, uf, n_pendentes)."""
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


# --- filtrar_ids_por_tipos -------------------------------------------------


def test_filtrar_ids_por_tipos_seleciona_so_quem_tem_o_tipo():
    saida = [
        segmentacao("logradouro", "numero"),
        segmentacao("referencia"),
        segmentacao("logradouro", "descricao_area"),
    ]
    selecionados = filtrar_ids_por_tipos(
        saida, [10, 11, 12], frozenset({"referencia", "descricao_area"})
    )
    assert selecionados == {11, 12}


def test_filtrar_ids_por_tipos_ignora_linha_ilegivel():
    selecionados = filtrar_ids_por_tipos(
        ["{nao é json", segmentacao("referencia")],
        [1, 2],
        frozenset({"referencia"}),
    )
    assert selecionados == {2}


def test_filtrar_ids_por_tipos_sem_segmentos_nao_seleciona():
    vazio = json.dumps({"segmentos": []})
    assert filtrar_ids_por_tipos([vazio], [1], frozenset({"referencia"})) == set()


def test_filtrar_ids_por_tipos_exige_mesmo_numero_de_linhas():
    with pytest.raises(ValueError):
        _ = filtrar_ids_por_tipos(
            [segmentacao("referencia")], [1, 2], frozenset({"referencia"})
        )


# --- validar_tipos_filtro --------------------------------------------------


def test_validar_tipos_aceita_tipo_do_modelo():
    assert validar_tipos(["Referencia", " descricao_area "], None) == frozenset(
        {"referencia", "descricao_area"}
    )


def test_validar_tipos_vazio_desliga_o_filtro():
    assert validar_tipos(None, None) == frozenset()
    assert validar_tipos([], None) == frozenset()


def test_validar_tipos_recusa_tipo_inexistente():
    with pytest.raises(BadParameter):
        _ = validar_tipos(["bairro"], None)


def test_validar_tipos_recusa_tipo_que_o_crf_nao_emite():
    # `ruido` existe na ontologia, mas o treinamento o colapsa em `O`.
    with pytest.raises(BadParameter):
        _ = validar_tipos(["ruido"], None)


# --- integração com o banco ------------------------------------------------


def test_pendentes_respeitam_o_filtro_do_crf():
    conn = banco_com([("A", "SP", 3), ("B", "RJ", 3)])
    aprovados = Filtros(ids=frozenset({2, 5}))

    assert len(pendentes(conn, Filtros())) == 6
    assert {linha.id for linha in pendentes(conn, aprovados)} == {2, 5}


def test_filtro_nao_inclui_linhas_ja_etiquetadas():
    conn = banco_com([("A", "SP", 2)])
    _ = conn.execute(
        "UPDATE enderecos SET resposta_llm = ? WHERE id = 1",
        (segmentacao("referencia"),),
    )
    conn.commit()
    aprovados = Filtros(ids=frozenset({1, 2}))

    assert {linha.id for linha in pendentes(conn, aprovados)} == {2}


# --- comando do segmentador ------------------------------------------------


def test_comando_segmentacao_usa_binario_informado():
    binario = Path("/opt/enderecobr/padronizar")
    assert comando_segmentacao(binario) == [str(binario), "segmentacao"]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
