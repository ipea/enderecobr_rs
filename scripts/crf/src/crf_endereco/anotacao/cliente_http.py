"""Cliente HTTP com retentativa e backoff."""

import random
import time
from typing import Any, cast

import requests
from rich.console import Console

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:156.0) Gecko/20100101 Firefox/156.0"
)


def _pode_retentar(status: int) -> bool:
    """Indica se o status HTTP merece nova tentativa.

    5xx e 429 são transientes; os demais 4xx significam que o servidor recusou
    o conteúdo (payload/schema), então repetir só gasta tempo.
    """
    return status == 429 or status >= 500


class ErroHTTP(RuntimeError):
    """Resposta de erro do servidor, com o corpo incluído para diagnóstico.

    `raise_for_status` só informa o status; o corpo é o que diz *por que* falhou
    (um 500 de backend costuma vir com `{"error": ...}`), e sem ele o erro de
    uma linha vira um `{"erro": "HTTPError: 500"}` inútil no banco.
    """

    def __init__(self, metodo: str, url: str, status: int, corpo: str) -> None:
        self.metodo = metodo
        self.url = url
        self.status = status
        self.corpo = corpo
        recorte = " ".join(corpo.split())[:800]
        super().__init__(
            f"{metodo} {url} → HTTP {status}: {recorte or '<corpo vazio>'}"
        )


class ClienteHTTP:
    """Cliente HTTP com retry para erros transientes.

    Concentraliza o backoff exponencial + jitter num único lugar, reusado tanto
    nas chamadas à LLM (`enviar_json`) quanto nas ferramentas de busca e fetch
    de páginas (`obter`).
    """

    def __init__(
        self,
        console: Console,
        n_tentativas: int = 5,
        delay_base: float = 2.0,
        timeout_conexao: float = 10.0,
    ) -> None:
        self.console: Console = console
        self.n_tentativas = n_tentativas
        self.delay_base = delay_base
        self.timeout_conexao = timeout_conexao
        self.sessao = requests.Session()
        self.sessao.trust_env = True

    def obter(
        self, url: str, *, timeout: float = 30.0, **kwargs: Any
    ) -> requests.Response:
        """GET com retry; retorna a resposta bruta."""
        return cast(requests.Response, self._requisitar("GET", url, timeout, **kwargs))

    def enviar_json(
        self,
        url: str,
        payload: dict[str, Any],
        *,
        timeout: float = 300.0,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """POST com retry; decodifica e retorna o corpo JSON."""
        return cast(
            dict[str, Any],
            self._requisitar(
                "POST", url, timeout, json=payload, decodificar=True, **kwargs
            ),
        )

    def _requisitar(
        self,
        metodo: str,
        url: str,
        timeout: float,
        *,
        decodificar: bool = False,
        **kwargs: Any,
    ) -> Any:
        """Executa uma requisição, reenviando em erros transientes.

        4xx (menos 429) falham na hora, com o corpo do servidor na mensagem.
        """
        ultimo_erro: Exception | None = None
        for tentativa in range(self.n_tentativas):
            try:
                resposta = self.sessao.request(
                    metodo, url, timeout=(self.timeout_conexao, timeout), **kwargs
                )
            except (requests.Timeout, requests.ConnectionError) as e:
                erro: Exception = e
            else:
                if resposta.ok:
                    if not decodificar:
                        return resposta
                    try:
                        return resposta.json()
                    except requests.JSONDecodeError:
                        erro = ErroHTTP(
                            metodo, url, resposta.status_code, resposta.text
                        )
                else:
                    erro = ErroHTTP(metodo, url, resposta.status_code, resposta.text)
                    if not _pode_retentar(resposta.status_code):
                        raise erro

            ultimo_erro = erro
            if tentativa == self.n_tentativas - 1:
                break
            delay = self.delay_base * (2**tentativa - 1) + random.uniform(0, 5)
            self.console.print(
                f"[yellow]Tentativa {tentativa + 1}/{self.n_tentativas} "
                f"falhou: {erro}. Retentando em {delay:.2f}s…[/yellow]"
            )
            time.sleep(delay)

        if isinstance(ultimo_erro, ErroHTTP):
            raise ultimo_erro
        detalhe = f": {ultimo_erro}" if ultimo_erro is not None else ""
        raise RuntimeError(
            f"{metodo} {url} falhou após {self.n_tentativas} tentativa(s){detalhe}"
        )
