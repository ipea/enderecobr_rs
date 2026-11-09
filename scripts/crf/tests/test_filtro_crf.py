import sqlite3
from collections.abc import Sequence
from pathlib import Path

import pytest
from typer import BadParameter

from crf_endereco.anotacao.filtro_crf import (
    Previsao,
    confianca_media,
    confianca_minima,
    filtrar_por_confianca,
    filtrar_por_tipos,
    tipos_das_tags,
    validar_tipos,
)
from crf_endereco.anotacao.pendentes import Filtros, padrao_busca, pendentes
from crf_endereco.dataset import criar_banco
from crf_endereco.segmentador_rust import comando_segmentacao


def previsao(
    identificador: int,
    tipos: Sequence[str] = (),
    *,
    menor: float = 1.0,
    media: float = 1.0,
) -> Previsao:
    """Previsao do CRF como o modelo a devolveria para um endereco."""
    return Previsao(
        id=identificador,
        tipos=frozenset(tipos),
        menor_confianca=menor,
        media_confianca=media,
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


# --- tipos_das_tags --------------------------------------------------------


def test_tipos_das_tags_extrai_o_tipo_do_rotulo_bio():
    tags = ["B_LOGRADOURO", "I_LOGRADOURO", "O", "B_NUCLEO_RURAL"]
    assert tipos_das_tags(tags) == frozenset({"logradouro", "nucleo_rural"})


def test_tipos_das_tags_sem_tags_nao_preve_nada():
    assert tipos_das_tags([]) == frozenset()


# --- confianca -------------------------------------------------------------


def test_confianca_minima_pega_o_token_mais_inseguro():
    marginais = [
        {"O": 0.02, "B_LOGRADOURO": 0.98},
        {"B_NUMERO": 0.55, "O": 0.45},
    ]

    assert confianca_minima(["B_LOGRADOURO", "B_NUMERO"], marginais) == 0.55


def test_confianca_media_media_os_tokens_previstos():
    marginais = [
        {"O": 0.02, "B_LOGRADOURO": 0.98},
        {"B_NUMERO": 0.55, "O": 0.45},
    ]

    assert confianca_media(["B_LOGRADOURO", "B_NUMERO"], marginais) == pytest.approx(
        0.765
    )


def test_confianca_sem_token_nao_esta_em_duvida():
    assert confianca_minima([], []) == 1.0
    assert confianca_media([], []) == 1.0


# --- filtros ---------------------------------------------------------------


def test_filtrar_por_tipos_seleciona_so_quem_tem_o_tipo():
    previsoes = [
        previsao(10, ["logradouro", "numero"]),
        previsao(11, ["referencia"]),
        previsao(12, ["logradouro", "nucleo_rural"]),
    ]

    selecionados = filtrar_por_tipos(
        previsoes, frozenset({"referencia", "nucleo_rural"})
    )

    assert selecionados == {11, 12}


def test_filtrar_por_confianca_usa_o_token_menos_confiavel():
    previsoes = [previsao(1, menor=0.95), previsao(2, menor=0.40, media=0.90)]

    assert filtrar_por_confianca(previsoes, 0.6) == {2}


def test_filtrar_por_confianca_media_olha_todos_os_tokens():
    previsoes = [
        previsao(1, menor=0.95, media=0.97),
        previsao(2, menor=0.4, media=0.55),
    ]

    assert filtrar_por_confianca(previsoes, 0.6, media=True) == {2}


def test_filtrar_por_confianca_empate_no_limiar_nao_marca():
    assert filtrar_por_confianca([previsao(1, menor=0.6, media=0.6)], 0.6) == set()
    assert (
        filtrar_por_confianca([previsao(1, menor=0.6, media=0.6)], 0.6, media=True)
        == set()
    )


# --- validar_tipos ---------------------------------------------------------


def test_validar_tipos_aceita_tipo_do_modelo():
    assert validar_tipos(["Referencia", " nucleo_rural "]) == frozenset(
        {"referencia", "nucleo_rural"}
    )


def test_validar_tipos_vazio_desliga_o_filtro():
    assert validar_tipos(None) == frozenset()
    assert validar_tipos([]) == frozenset()


def test_validar_tipos_recusa_tipo_inexistente():
    with pytest.raises(BadParameter):
        _ = validar_tipos(["bairro"])


def test_validar_tipos_recusa_tipo_que_o_crf_nao_emite():
    # `ruido` existe na ontologia, mas o treinamento o colapsa em `O`.
    with pytest.raises(BadParameter):
        _ = validar_tipos(["ruido"])


# --- padrao de busca -------------------------------------------------------


def test_padrao_busca_ignora_caixa_acento_e_espacos_extras():
    assert padrao_busca("  Asa   Norte ") == "%ASA NORTE%"


def test_padrao_busca_nao_deixa_curinga_escapar_do_trecho():
    assert padrao_busca("100%_x") == r"%100\%\_X%"


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
        ('{"segmentos": []}',),
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
