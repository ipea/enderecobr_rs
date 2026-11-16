import json
import sqlite3
from collections.abc import Sequence
from pathlib import Path
from typing import cast

import pytest
import sklearn_crfsuite
from typer import BadParameter

from crf_endereco.anotacao.filtro_crf import (
    Previsao,
    confianca_media,
    confianca_minima,
    divergencias,
    filtrar_por_confianca,
    filtrar_por_tipos,
    parse_faixa,
    tipos_das_tags,
    validar_tipos,
)
from crf_endereco.anotacao.pendentes import Filtros, padrao_busca, pendentes
from crf_endereco.dataset import criar_banco
from crf_endereco.modelo.crf import Exemplos
from crf_endereco.segmentador_rust import comando_segmentacao


def previsao(
    identificador: int,
    tipos: Sequence[str] = (),
    *,
    menor: float = 1.0,
    media: float = 1.0,
) -> Previsao:
    """Previsao do CRF como o modelo a devolveria para um endereco."""
    # Nome do endereco e do token menos confiavel; nao sao segredo nenhum (o
    # bandit acha que `pior_token=` com literal e senha e reclama).
    endereco, pior = "RUA", tipos[0].upper() if tipos else None
    return Previsao(
        id=identificador,
        tags=tuple(f"B_{tipo.upper()}" for tipo in tipos),
        tipos=frozenset(tipos),
        menor_confianca=menor,
        media_confianca=media,
        pior_token=endereco,
        pior_tag=f"B_{pior}" if pior else "O",
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


def anotar(
    conn: sqlite3.Connection, id_linha: int, revisado_por: str | None = None
) -> None:
    """Marca a linha como anotada com sucesso (e revisada por um modelo)."""
    # Revisado vem sempre com histórico: é o par que `gravar_resposta` grava.
    meta = (
        json.dumps(
            {"revisado": {"modelo": revisado_por}, "revisoes": [{"resposta": {}}]}
        )
        if revisado_por
        else "{}"
    )
    _ = conn.execute(
        "UPDATE enderecos SET resposta_llm = '{\"segmentos\": []}', meta = ? WHERE id = ?",
        (meta, id_linha),
    )
    conn.commit()


class CrfFake:
    """CRF que devolve uma previsao pronta em vez de prever."""

    def __init__(self, previsto: list[list[str]]) -> None:
        self.previsto = previsto

    def predict(self, _x: object) -> list[list[str]]:
        return self.previsto


def exemplos_com(hashes: list[str], rotulos: list[list[str]]) -> Exemplos:
    return Exemplos(
        x=[[{"bias": 1.0}] for _ in hashes],
        y=rotulos,
        tokens=[["RUA"] for _ in hashes],
        categorias=[["origem", "SP"] for _ in hashes],
        hashes=hashes,
    )


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


def test_confianca_media_media_geometrica_dos_tokens_previstos():
    marginais = [
        {"O": 0.02, "B_LOGRADOURO": 0.98},
        {"B_NUMERO": 0.55, "O": 0.45},
    ]

    # Media geometrica de 0.98 e 0.55, nao a aritmetica (0.765).
    assert confianca_media(["B_LOGRADOURO", "B_NUMERO"], marginais) == pytest.approx(
        0.734166, abs=1e-6
    )


def test_confianca_media_zera_com_probabilidade_nula():
    assert confianca_media(["B_NUMERO"], [{"B_NUMERO": 0.0}]) == 0.0


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

    assert filtrar_por_confianca(previsoes, (0.0, 0.6)) == {2}


def test_filtrar_por_confianca_media_olha_todos_os_tokens():
    previsoes = [
        previsao(1, menor=0.95, media=0.97),
        previsao(2, menor=0.4, media=0.55),
    ]

    assert filtrar_por_confianca(previsoes, (0.0, 0.6), media=True) == {2}


def test_filtrar_por_confianca_empate_no_limiar_nao_marca():
    assert (
        filtrar_por_confianca([previsao(1, menor=0.6, media=0.6)], (0.0, 0.6)) == set()
    )
    assert (
        filtrar_por_confianca(
            [previsao(1, menor=0.6, media=0.6)], (0.0, 0.6), media=True
        )
        == set()
    )


def test_filtrar_por_confianca_respeita_o_minimo_da_faixa():
    previsoes = [
        previsao(1, menor=0.20, media=0.20),
        previsao(2, menor=0.55, media=0.55),
        previsao(3, menor=0.85, media=0.85),
    ]

    # Faixa [0.4, 0.8): nem o caso perdido nem o caso facil entram.
    assert filtrar_por_confianca(previsoes, (0.4, 0.8), media=True) == {2}


def test_parse_faixa_aceita_valor_unico_e_faixa():
    assert parse_faixa(None, "--incertos") is None
    assert parse_faixa("0.8", "--incertos") == (0.0, 0.8)
    assert parse_faixa(" 0.6 , 0.8 ", "--incertos") == (0.6, 0.8)


def test_parse_faixa_recusa_faixa_invertida_ou_fora_de_zero_um():
    for valor in (
        "0.8,0.6",
        "0.8,0.8",
        "-0.1,0.5",
        "0.5,1.5",
        "0.5,0.6,0.7",
        "",
        "a,b",
    ):
        with pytest.raises(BadParameter):
            _ = parse_faixa(valor, "--incertos")


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


def test_anotados_troca_os_pendentes_pelas_linhas_ja_etiquetadas():
    conn = banco_com([("A", "SP", 2)])
    anotar(conn, 1)

    assert {linha.id for linha in pendentes(conn, Filtros(anotados=True))} == {1}


def test_filtro_por_hash_recorta_um_conjunto_de_linhas():
    conn = banco_com([("A", "SP", 3)])

    linhas = pendentes(conn, Filtros(hashes=frozenset({"h2", "h3"})))

    assert {linha.hash for linha in linhas} == {"h2", "h3"}


def test_linha_ja_revisada_pelo_modelo_fica_de_fora():
    conn = banco_com([("A", "SP", 2)])
    anotar(conn, 1, revisado_por="tagger_v13")
    anotar(conn, 2, revisado_por="tagger_v12")

    ficam = pendentes(conn, Filtros(anotados=True, pular_revisados_por="tagger_v13"))

    # a revisao de outro modelo nao tira a linha da fila deste
    assert {linha.id for linha in ficam} == {2}


def test_revisados_pega_so_quem_tem_historico_de_reetiquetacao():
    conn = banco_com([("A", "SP", 3)])
    anotar(conn, 1, revisado_por="tagger_v13")
    anotar(conn, 2)

    linhas = pendentes(conn, Filtros(anotados=True, revisados=True))

    assert {linha.id for linha in linhas} == {1}


# --- divergencia entre previsao e rotulo -----------------------------------


def test_divergencias_pega_so_onde_o_modelo_erra_o_proprio_rotulo():
    exemplos = exemplos_com(["h1", "h2"], [["B_NUMERO", "O"], ["B_NUMERO", "O"]])
    crf = cast(
        sklearn_crfsuite.CRF,
        cast(object, CrfFake([["B_NUMERO", "O"], ["B_NUMERO", "B_NUMERO"]])),
    )

    achados = divergencias(crf, exemplos)

    assert [(achado.hash, achado.pares) for achado in achados] == [
        ("h2", (("O", "B_NUMERO"),))
    ]


def test_divergencias_sem_erro_nao_devolve_nada():
    exemplos = exemplos_com(["h1"], [["O"]])
    crf = cast(sklearn_crfsuite.CRF, cast(object, CrfFake([["O"]])))

    assert divergencias(crf, exemplos) == []


# --- comando do segmentador ------------------------------------------------


def test_comando_segmentacao_usa_binario_informado():
    binario = Path("/opt/enderecobr/padronizar")
    assert comando_segmentacao(binario) == [str(binario), "segmentacao"]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
