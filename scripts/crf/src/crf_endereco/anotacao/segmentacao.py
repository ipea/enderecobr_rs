"""Loop reAct que segmenta um endereco."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from rich.console import Console

from crf_endereco.anotacao.cliente_http import ClienteHTTP
from crf_endereco.anotacao.config import Config
from crf_endereco.anotacao.ferramentas import Ferramentas, criar_ferramentas
from crf_endereco.anotacao.prompt import (
    renderizar_prompt_sistema,
    renderizar_prompt_usuario,
)
from crf_endereco.anotacao.resposta import (
    ErroSegmentacao,
    RespostaFinal,
    estruturar_resposta_modelo,
    processar_resultado_final,
    validar_resposta_final,
)


@dataclass
class Contexto:
    """Reúne a configuração, o cliente HTTP e as ferramentas de uma execução."""

    config: Config
    cliente: ClienteHTTP
    ferramentas: Ferramentas
    console: Console

    @classmethod
    def criar(cls, config: Config, console: Console) -> Contexto:
        cliente = ClienteHTTP(console=console)
        return cls(
            config=config,
            cliente=cliente,
            ferramentas=Ferramentas(config, cliente),
            console=console,
        )

    def fechar(self) -> None:
        self.ferramentas.fechar()

def segmentar(
    contexto: Contexto,
    endereco: str,
    extras: str,
    *,
    n_iter: int = 10,
    tolerancia_erro: int = 2,
) -> RespostaFinal:
    """Roda o loop reAct até obter uma segmentação válida."""
    config = contexto.config
    console = contexto.console
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": renderizar_prompt_sistema(config)},
        {
            "role": "user",
            "content": renderizar_prompt_usuario(endereco, extras, n_iter),
        },
    ]
    erros_consecutivos = 0

    for i in range(n_iter):
        console.rule(f"Iteração {i + 1}/{n_iter}")

        resposta = estruturar_resposta_modelo(
            realizar_requisicao(contexto.cliente, config, messages)
        )
        messages.append(resposta.message_original)

        if resposta.raciociono:
            console.print(resposta.raciociono, style="dim italic")
        if resposta.resposta:
            console.print(resposta.resposta)

        chamada_final = resposta.obter_resposta_final()
        if chamada_final is not None:
            resultado = processar_resultado_final(chamada_final)
            visualizacao, erro = validar_resposta_final(endereco, resultado)
            console.print(visualizacao)

            if erro is None:
                return resultado

            erros_consecutivos += 1
            if erros_consecutivos > tolerancia_erro:
                raise ErroSegmentacao(
                    f"Validação falhou {erros_consecutivos} vezes seguidas:\n{erro}"
                )
            messages.append(
                {
                    "role": "user",
                    "content": f"An error occurred while validating your segmentation. Fix it and submit again.\n{erro}",
                }
            )
            continue

        for chamada in resposta.tool_calls:
            console.print(f"[bold]{chamada.nome}[/bold] {chamada.argumentos}")
            saida = contexto.ferramentas.despachar(chamada)
            console.print(saida)
            messages.append(
                {"role": "tool", "tool_call_id": chamada.idx, "content": saida}
            )

        if i == n_iter - 1:
            console.print("[bold red]Última iteração[/bold red]")
            messages.append(
                {
                    "role": "user",
                    "content": "Final round - Give your answer now or abstain",
                }
            )

    raise ErroSegmentacao(f"Sem resposta final após {n_iter} iterações.")


def realizar_requisicao(
    cliente: ClienteHTTP, config: Config, messages: list[dict[str, Any]]
) -> dict[str, Any]:
    return cliente.enviar_json(
        config.url_chat,
        {
            "model": config.api_model,
            "messages": messages,
            "tools": criar_ferramentas(config),
            "temperature": 0.3,
        },
        headers={
            "Authorization": f"Bearer {config.api_key}",
            "Content-Type": "application/json",
        },
    )
