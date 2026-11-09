"""Guardas da ferramenta de SQL exposta à LLM."""

import pytest

from crf_endereco.anotacao.ferramentas import validar_consulta


def test_validar_consulta_aceita_leitura():
    assert validar_consulta("  select 1;  ") == "select 1"
    assert validar_consulta("WITH x AS (SELECT 1) SELECT * FROM x").startswith("WITH")


@pytest.mark.parametrize(
    "sql",
    [
        "COPY (SELECT 1) TO '/tmp/x.parquet'",
        "INSTALL httpfs",
        "ATTACH 'outro.db'",
        "DELETE FROM cnefe",
        "SELECT 1; SELECT 2",
        "",
    ],
)
def test_validar_consulta_recusa_escrita_e_multiplas(sql: str):
    with pytest.raises(ValueError):
        _ = validar_consulta(sql)


@pytest.mark.parametrize(
    "sql",
    ["SELECT * FROM read_csv('/etc/passwd')", "SELECT * FROM glob('/**')"],
)
def test_validar_consulta_recusa_leitura_de_arquivo(sql: str):
    with pytest.raises(ValueError):
        _ = validar_consulta(sql)
