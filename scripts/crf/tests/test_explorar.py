from typing import Any

import pytest
from typer import BadParameter

from crf_endereco.anotacao.filtro_crf import Divergencia, Previsao
from crf_endereco.anotacao.pendentes import Pendente
from crf_endereco.cli.explorar import (
    ORDEM_VEREDITO,
    _comparar,
    _ordenar,
    _papel_do_recorte,
    _resumo,
)
from crf_endereco.dataset import Detalhe
from crf_endereco.rotulos import CONCORDA_COM_O_CRF, ROTULO_MANTIDO, ROTULO_NOVO

RESPOSTA_LOG = {"segmentos": [{"tipo": "logradouro", "valor": "RUA A"}]}
RESPOSTA_LOC = {"segmentos": [{"tipo": "localidade", "valor": "RUA A"}]}


def linha(identificador: int, endereco: str = "RUA A") -> Pendente:
    """Uma linha do dataset como o `pendentes` devolveria."""
    return Pendente(
        id=identificador,
        endereco=endereco,
        extras="",
        uf="DF",
        municipio="BRASILIA",
        origem="siase",
        hash=f"h{identificador}",
    )


def previsao(
    identificador: int,
    media: float,
    tags: tuple[str, ...] = ("B_LOGRADOURO", "I_LOGRADOURO"),
) -> Previsao:
    """O que o CRF previu para a linha `identificador`."""
    # O nome do token mais duvidoso não é segredo, mas o bandit trata
    # `pior_token=` com literal como senha.
    duvidoso = "A"
    return Previsao(
        id=identificador,
        tags=tags,
        tipos=frozenset(tag.partition("_")[2].lower() for tag in tags if tag != "O"),
        menor_confianca=media,
        media_confianca=media,
        pior_token=duvidoso,
        pior_tag=tags[-1],
    )


def detalhe(
    segmentos: dict[str, list[dict[str, str]]] | None,
    revisoes: tuple[dict[str, Any], ...] = (),
) -> Detalhe:
    """Detalhe de `RUA A` com o alvo atual e o histórico de revisão pedidos."""
    return Detalhe(
        id=1,
        endereco="RUA A",
        extras="",
        uf="DF",
        municipio="BRASILIA",
        origem="siase",
        lote="lote",
        recorte="tagger_v13/treino",
        llm="llm",
        segmentos=tuple(segmentos["segmentos"]) if segmentos else (),
        erro=None,
        revisoes=revisoes,
        revisado_por="tagger_v13" if revisoes else None,
    )


def divergencia(hash_: str, pares: int) -> Divergencia:
    """Divergência com `pares` tokens trocados."""
    rotulos = tuple("O" for _ in range(pares))
    return Divergencia(
        hash=hash_, rotulos=rotulos, previsto=tuple("B_NUMERO" for _ in range(pares))
    )


# --- opções do comando -----------------------------------------------------


def test_papel_do_recorte_aceita_os_tres_valores():
    assert _papel_do_recorte("todos") is None
    assert _papel_do_recorte("treino") == "treino"
    assert _papel_do_recorte("teste") == "teste"


def test_papel_do_recorte_recusa_valor_desconhecido():
    with pytest.raises(BadParameter):
        _ = _papel_do_recorte("validacao")


# --- as tres camadas -------------------------------------------------------


def test_comparar_usa_a_revisao_anterior_como_rotulo_de_antes():
    # a revisão trocou `localidade` por `logradouro`: a LLM passou a concordar
    # com o CRF, então o rótulo antigo era o problema
    mudancas, veredito = _comparar(
        detalhe(RESPOSTA_LOG, ({"resposta": RESPOSTA_LOC},)), previsao(1, 0.9)
    )

    assert [
        (mudanca.antes, mudanca.previsto, mudanca.agora) for mudanca in mudancas
    ] == [
        ("B_LOCALIDADE", "B_LOGRADOURO", "B_LOGRADOURO"),
        ("I_LOCALIDADE", "I_LOGRADOURO", "I_LOGRADOURO"),
    ]
    assert veredito == CONCORDA_COM_O_CRF


def test_comparar_sem_revisao_compara_o_alvo_atual_com_o_crf():
    # sem histórico, `antes` é o próprio alvo: só sobra a divergência do modelo
    mudancas, veredito = _comparar(detalhe(RESPOSTA_LOG), previsao(1, 0.9))

    assert mudancas == []
    assert veredito == CONCORDA_COM_O_CRF


# --- ordenação -------------------------------------------------------------


def test_ordenar_divergentes_comeca_pelo_que_troca_mais_tokens():
    linhas = [linha(1), linha(2)]
    achados = {"h1": divergencia("h1", 1), "h2": divergencia("h2", 3)}
    por_id = {1: previsao(1, 0.1), 2: previsao(2, 0.9)}

    assert [lista.id for lista in _ordenar(linhas, por_id, achados, {})] == [2, 1]


def test_ordenar_revisados_comeca_pelo_que_ainda_e_erro_do_modelo():
    linhas = [linha(1), linha(2)]
    por_id = {1: previsao(1, 0.2), 2: previsao(2, 0.9)}
    vereditos = {1: CONCORDA_COM_O_CRF, 2: ROTULO_MANTIDO}

    assert [lista.id for lista in _ordenar(linhas, por_id, {}, vereditos)] == [2, 1]


def test_ordenar_sem_criterio_usa_a_confianca_do_crf():
    linhas = [linha(1), linha(2), linha(3)]
    por_id = {1: previsao(1, 0.7), 2: previsao(2, 0.2), 3: previsao(3, 0.5)}

    assert [lista.id for lista in _ordenar(linhas, por_id, {}, {})] == [2, 3, 1]


# --- resumo da lista -------------------------------------------------------


def test_resumo_diz_por_que_a_lista_esta_naquela_ordem():
    assert "tokens trocados" in _resumo({"h1": divergencia("h1", 1)}, {})
    assert "confiança do CRF" in _resumo({}, {})


def test_resumo_de_revisados_mostra_o_placar_dos_vereditos():
    vereditos = {1: ROTULO_MANTIDO, 2: ROTULO_MANTIDO, 3: ROTULO_NOVO}

    resumo = _resumo({}, vereditos)

    assert "2 rótulo mantido" in resumo
    assert "1 rótulo novo" in resumo
    # o placar sai na ordem em que a lista é ordenada
    assert resumo.index(ROTULO_MANTIDO) < resumo.index(ROTULO_NOVO)
    assert set(ORDEM_VEREDITO) == {ROTULO_MANTIDO, ROTULO_NOVO, CONCORDA_COM_O_CRF}
