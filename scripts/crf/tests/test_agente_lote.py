import json
from typing import Any, cast

from rich.console import Console

from crf_endereco.anotacao.agente import (
    Agente,
    Chamada,
    Pedido,
    _chamadas,
    _respostas,
    prompt_usuario,
    segmentar,
)
from crf_endereco.anotacao.cliente_http import ClienteHTTP
from crf_endereco.anotacao.ferramentas import Ferramentas
from crf_endereco.anotacao.lote import agrupar, compor_lotes
from crf_endereco.anotacao.pendentes import Pendente
from crf_endereco.config import Config


class ClienteFake:
    """Devolve as mensagens roteirizadas e guarda a conversa enviada."""

    def __init__(self, roteiro: list[dict[str, Any]]) -> None:
        self.roteiro = roteiro
        self.enviados: list[list[dict[str, Any]]] = []

    def enviar_json(
        self, _url: str, payload: dict[str, Any], **_kwargs: Any
    ) -> dict[str, Any]:
        # copia: `messages` continua crescendo depois do envio
        self.enviados.append(list(payload["messages"]))
        return {"choices": [{"message": self.roteiro.pop(0)}]}


class FerramentasFake:
    """Ferramentas que nunca sao chamadas nestes testes."""

    def despachar(self, nome: str, argumentos: dict[str, Any]) -> str:
        raise AssertionError(f"ferramenta inesperada: {nome} {argumentos}")


def chamada_com(argumentos: dict[str, Any]) -> Chamada:
    """Chamada `responder` com os argumentos dados, como a LLM mandaria."""
    return _chamadas(
        {
            "tool_calls": [
                {
                    "id": "call-1",
                    "function": {
                        "name": "responder",
                        "arguments": json.dumps(argumentos),
                    },
                }
            ]
        }
    )[0]


def mensagem(por_indice: dict[int, list[tuple[str, str]]]) -> dict[str, Any]:
    """Mensagem da LLM com uma chamada `responder` para os indices dados."""
    respostas = [
        {
            "indice": indice,
            "segmentos": [{"valor": valor, "tipo": tipo} for tipo, valor in segmentos],
        }
        for indice, segmentos in por_indice.items()
    ]
    return {
        "tool_calls": [
            {
                "id": "call-1",
                "function": {
                    "name": "responder",
                    "arguments": json.dumps({"respostas": respostas}),
                },
            }
        ]
    }


def criar_agente_fake(roteiro: list[dict[str, Any]]) -> tuple[Agente, ClienteFake]:
    cliente = ClienteFake(roteiro)
    return (
        Agente(
            config=Config(api_url="x", api_key="x", api_model="x", com_cnefe=False),
            cliente=cast(ClienteHTTP, cast(object, cliente)),
            ferramentas=cast(Ferramentas, cast(object, FerramentasFake())),
            console=Console(quiet=True),
        ),
        cliente,
    )


def pendente(i: int, uf: str, municipio: str, origem: str = "cneas") -> Pendente:
    return Pendente(
        id=i,
        endereco=f"RUA {i}, {i}",
        extras="",
        uf=uf,
        municipio=municipio,
        origem=origem,
        hash=f"h{i}",
    )


def test_prompt_usuario_numera_os_enderecos_com_o_seu_contexto():
    texto = prompt_usuario([Pedido("RUA A, 1", "Municipio: X"), Pedido("RUA B, 2")], 5)

    assert "[1]" in texto
    assert "[2]" in texto
    assert "Municipio: X" in texto
    assert "You have 5 rounds." in texto


def test_respostas_ignora_indice_fora_do_lote_e_repetido():
    respostas = _respostas(
        chamada_com(
            {
                "respostas": [
                    {"indice": 3, "segmentos": [{"valor": "A", "tipo": "outros"}]},
                    {"indice": 1, "segmentos": [{"valor": "B", "tipo": "outros"}]},
                    {"indice": 1, "segmentos": [{"valor": "C", "tipo": "outros"}]},
                ]
            }
        ),
        total=2,
    )

    assert list(respostas) == [0]
    assert respostas[0].segmentos[0].valor == "B"


def test_segmentar_cobra_de_volta_so_o_indice_sem_resposta():
    agente, cliente = criar_agente_fake(
        [
            mensagem({1: [("outros", "RUA A"), ("outros", ", 1")]}),
            mensagem({2: [("outros", "RUA B"), ("outros", ", 2")]}),
        ]
    )

    resultado = segmentar(
        agente, [Pedido("RUA A, 1"), Pedido("RUA B, 2")], n_iter=3, tolerancia_erro=2
    )

    assert set(resultado.aceitas) == {0, 1}
    assert not resultado.falhas
    correcao = str(cliente.enviados[1][-1]["content"])
    assert "[2] RUA B, 2" in correcao
    assert "[1] RUA A, 1" not in correcao


def test_segmentar_falha_so_o_endereco_que_nao_foi_verbatim():
    agente, _ = criar_agente_fake([mensagem({1: [("outros", "RUA QUE NAO EXISTE")]})])

    resultado = segmentar(agente, [Pedido("RUA A, 1")], n_iter=1, tolerancia_erro=0)

    assert not resultado.aceitas
    assert "Could not locate segment" in resultado.falhas[0]


def test_segmentar_sem_resposta_marca_todos_com_falha():
    agente, _ = criar_agente_fake([{"content": "pensando"}, {"content": "pensando"}])

    resultado = segmentar(
        agente, [Pedido("RUA A, 1"), Pedido("RUA B, 2")], n_iter=2, tolerancia_erro=2
    )

    assert not resultado.aceitas
    assert set(resultado.falhas) == {0, 1}
    assert "iteracoes" in resultado.falhas[0]


def test_agrupar_junta_a_mesma_celula_e_respeita_o_tamanho():
    linhas = [
        pendente(1, "SP", "SAO PAULO"),
        pendente(2, "RJ", "RIO DE JANEIRO"),
        pendente(3, "SP", "SAO PAULO"),
        pendente(4, "SP", "SAO PAULO"),
        pendente(5, "RJ", "RIO DE JANEIRO"),
    ]

    grupos = agrupar(linhas, 2)

    assert [[linha.id for linha in grupo] for grupo in grupos] == [
        [1, 3],
        [2, 5],
        [4],
    ]


def test_agrupar_com_tamanho_um_nao_muda_o_sorteio():
    linhas = [pendente(1, "SP", "SAO PAULO"), pendente(2, "RJ", "RIO DE JANEIRO")]

    assert [[linha.id for linha in grupo] for grupo in agrupar(linhas, 1)] == [
        [1],
        [2],
    ]


def test_agrupar_fecha_a_sobra_da_celula_com_vizinhos_do_municipio():
    # Tres de (SP, CAMPINAS, cneas) nao fecham um lote de 2 sozinhos na celula:
    # o que sobra junta-se a outra origem do mesmo municipio, nunca de outro.
    linhas = [
        pendente(1, "SP", "CAMPINAS", "cneas"),
        pendente(2, "SP", "CAMPINAS", "cneas"),
        pendente(3, "SP", "CAMPINAS", "cneas"),
        pendente(4, "SP", "CAMPINAS", "aneel_uc_pj"),
        pendente(5, "RJ", "NITEROI", "cneas"),
    ]

    grupos = agrupar(linhas, 2)

    assert [[linha.id for linha in grupo] for grupo in grupos] == [[1, 2], [3, 4], [5]]


def test_agrupar_nao_mistura_municipios_nem_em_sobra():
    linhas = [
        pendente(1, "SP", "CAMPINAS", "cneas"),
        pendente(2, "SP", "SANTOS", "cneas"),
        pendente(3, "SP", "CAMPINAS", "aneel_uc_pj"),
    ]

    grupos = agrupar(linhas, 4)

    assert {frozenset(linha.id for linha in grupo) for grupo in grupos} == {
        frozenset({1, 3}),
        frozenset({2}),
    }


def test_compor_lotes_corta_em_enderecos_e_nao_em_lotes():
    # O caso do problema: 5 celulas com 2 enderecos cada, limite de 6. Com o
    # limite aplicado antes do agrupamento davam 6 lotes de 1; aqui enchem.
    linhas = [pendente(i, "SP", f"MUNICIPIO {i % 5}") for i in range(1, 11)]

    grupos = compor_lotes(linhas, 2, 6)

    assert [len(grupo) for grupo in grupos] == [2, 2, 2]
    assert sum(len(grupo) for grupo in grupos) == 6


def test_compor_lotes_deixa_o_ultimo_lote_menor_para_nao_passar_do_limite():
    linhas = [pendente(1, "SP", "CAMPINAS"), pendente(2, "SP", "CAMPINAS")]
    linhas += [pendente(3, "RJ", "NITEROI"), pendente(4, "RJ", "NITEROI")]

    grupos = compor_lotes(linhas, 2, 3)

    assert [len(grupo) for grupo in grupos] == [2, 1]
