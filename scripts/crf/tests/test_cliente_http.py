import json
import time
from pathlib import Path
from typing import Any

import pytest
import requests
from rich.console import Console

from crf_endereco.anotacao.cliente_http import ClienteHTTP, ErroHTTP, _pode_retentar
from crf_endereco.anotacao.config import Config
from crf_endereco.anotacao.ferramentas import criar_ferramentas


class RespostaFalsa(requests.Response):
    """`requests.Response` de mentira: só o que `ClienteHTTP` lê (sem rede)."""

    def __init__(self, status_code: int, corpo: str = "") -> None:
        super().__init__()
        self.status_code = status_code
        self.corpo = corpo

    @property
    def ok(self) -> bool:
        return self.status_code < 400

    @property
    def text(self) -> str:
        return self.corpo

    def json(self, **kwargs: Any) -> Any:
        try:
            return json.loads(self.corpo) if self.corpo else {}
        except json.JSONDecodeError as e:
            raise requests.JSONDecodeError(str(e), self.corpo, 0) from e


class SessaoFalsa(requests.Session):
    """Sessão que devolve as respostas na ordem e conta as chamadas."""

    def __init__(self, respostas: list[RespostaFalsa]) -> None:
        super().__init__()
        self.respostas = respostas
        self.chamadas = 0

    def request(self, *args: Any, **kwargs: Any) -> requests.Response:
        resposta = self.respostas[min(self.chamadas, len(self.respostas) - 1)]
        self.chamadas += 1
        return resposta


def cliente_com(respostas: list[RespostaFalsa], n_tentativas: int = 3) -> ClienteHTTP:
    cliente = ClienteHTTP(console=Console(quiet=True), n_tentativas=n_tentativas)
    cliente.sessao = SessaoFalsa(respostas)
    return cliente


def chamadas_de(cliente: ClienteHTTP) -> int:
    sessao = cliente.sessao
    assert isinstance(sessao, SessaoFalsa)
    return sessao.chamadas


def sem_espera(*_args: object) -> None:
    """`time.sleep` no-op (o backoff não deve custar tempo nos testes)."""


@pytest.fixture(autouse=True)
def sem_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(time, "sleep", sem_espera)


# --- política de retry -----------------------------------------------------


@pytest.mark.parametrize(
    "status,esperado",
    [
        (200, False),
        (400, False),
        (401, False),
        (404, False),
        (429, True),
        (500, True),
        (503, True),
    ],
)
def test_pode_retentar(status: int, esperado: bool):
    assert _pode_retentar(status) is esperado


def test_retenta_5xx_e_devolve_sucesso():
    cliente = cliente_com(
        [RespostaFalsa(500, '{"error": "boom"}'), RespostaFalsa(200, '{"ok": 1}')]
    )
    assert cliente.enviar_json("https://exemplo/api", {}) == {"ok": 1}
    assert chamadas_de(cliente) == 2


def test_retenta_429():
    cliente = cliente_com([RespostaFalsa(429), RespostaFalsa(200, "{}")])
    assert cliente.enviar_json("https://exemplo/api", {}) == {}
    assert chamadas_de(cliente) == 2


def test_erro_5xx_final_traz_o_corpo_do_servidor():
    corpo = '{"error":{"message":"Internal server error","type":"server_error"}}'
    cliente = cliente_com([RespostaFalsa(500, corpo)], n_tentativas=2)

    with pytest.raises(ErroHTTP) as erro:
        _ = cliente.enviar_json("https://exemplo/api", {})

    assert erro.value.status == 500
    assert "Internal server error" in str(erro.value)
    assert chamadas_de(cliente) == 2  # esgotou as tentativas


def test_4xx_falha_na_primeira_tentativa():
    cliente = cliente_com([RespostaFalsa(400, '{"error": "schema inválido"}')])

    with pytest.raises(ErroHTTP) as erro:
        _ = cliente.enviar_json("https://exemplo/api", {})

    assert erro.value.status == 400
    assert "schema inválido" in str(erro.value)
    assert chamadas_de(cliente) == 1


def test_json_invalido_vira_erro_com_corpo():
    cliente = cliente_com([RespostaFalsa(200, "<html>manutencao</html>")], n_tentativas=1)

    with pytest.raises(ErroHTTP) as erro:
        _ = cliente.enviar_json("https://exemplo/api", {})

    assert "manutencao" in str(erro.value)


def test_obter_devolve_a_resposta_bruta():
    resposta = RespostaFalsa(200, "conteudo")
    cliente = cliente_com([resposta])
    assert cliente.obter("https://exemplo/pagina") is resposta


# --- schema das ferramentas ------------------------------------------------


def config(
    *, tools_estritas: bool = False, searx_url: str | None = "https://busca"
) -> Config:
    return Config(
        api_url="https://exemplo/api",
        api_key="chave",
        api_model="modelo",
        cnefe_path="/cnefe.parquet",
        municipios_path=Path("municipios.csv"),
        searx_url=searx_url,
        tools_estritas=tools_estritas,
    )


def test_ferramentas_nao_usam_strict_por_padrao():
    for ferramenta in criar_ferramentas(config()):
        assert "strict" not in ferramenta["function"]


def test_ferramentas_usam_strict_quando_configurado():
    for ferramenta in criar_ferramentas(config(tools_estritas=True)):
        assert ferramenta["function"]["strict"] is True


def test_ferramentas_incluem_busca_so_com_searx():
    com_busca = {f["function"]["name"] for f in criar_ferramentas(config())}
    sem_busca = {
        f["function"]["name"] for f in criar_ferramentas(config(searx_url=None))
    }
    assert "search" in com_busca
    assert "search" not in sem_busca


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
