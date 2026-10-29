"""Agente que segmenta um endereco: prompt, ferramentas e loop reAct."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rich.console import Console

from crf_endereco.anotacao.cliente_http import ClienteHTTP
from crf_endereco.anotacao.ferramentas import Ferramentas, criar_ferramentas
from crf_endereco.config import Config
from crf_endereco.ui import console as console_padrao

DIR_PROMPT = Path(__file__).resolve().parent
TEMPLATE_PROMPT = DIR_PROMPT / "prompt_sistema.md"
EXEMPLOS = DIR_PROMPT / "exemplos.md"
SCHEMA_CNEFE = DIR_PROMPT / "cnefe_schema.md"

# `str.isspace()` e mais amplo que o `u8::is_ascii_whitespace` usado pelo Rust
# (inclui NBSP, por exemplo); o conjunto explicito mantem as implementacoes
# equivalentes.
ESPACOS_ASCII = frozenset(" \t\n\x0c\r")


class ErroSegmentacao(RuntimeError):
    """Nao foi possivel obter uma segmentacao valida."""


@dataclass(frozen=True)
class Segmento:
    valor: str
    tipo: str


@dataclass(frozen=True)
class Chamada:
    """Uma tool call da LLM."""

    id: str
    nome: str
    argumentos: dict[str, Any]


@dataclass(frozen=True)
class Resposta:
    """Resposta final da LLM: os segmentos e o comentario opcional."""

    segmentos: list[Segmento]
    comentario: str | None = None


@dataclass(frozen=True)
class Agente:
    """Config, cliente HTTP e ferramentas de uma execucao (uma por thread)."""

    config: Config
    cliente: ClienteHTTP
    ferramentas: Ferramentas
    console: Console


def criar_agente(config: Config, console: Console = console_padrao) -> Agente:
    """Monta o agente de uma execucao (abre conexao DuckDB das ferramentas)."""
    cliente = ClienteHTTP(console=console)
    return Agente(
        config=config,
        cliente=cliente,
        ferramentas=Ferramentas(config, cliente),
        console=console,
    )


def fechar_agente(agente: Agente) -> None:
    agente.ferramentas.fechar()


def prompt_sistema(config: Config) -> str:
    """Preenche o template do prompt de sistema com as secoes disponiveis."""
    ferramentas = [
        "- `responder`: submit the final result. Always use this tool to answer.",
        (
            "- `search`: search across several search engines to learn what an "
            "unknown abbreviation or place name means."
        ),
        "- `fetch_url`: fetch a URL and return its content as markdown (markitdown).",
    ]
    if config.com_cnefe:
        ferramentas.insert(
            1,
            "- `sql_query`: query CNEFE in DuckDB. Restrict by município and/or "
            "uf, always use LIMIT and avoid SELECT *.",
        )
    template = TEMPLATE_PROMPT.read_text(encoding="utf-8")
    return (
        template.replace("{secao_ferramentas}", "\n".join(ferramentas))
        .replace(
            "{secao_cnefe}",
            SCHEMA_CNEFE.read_text(encoding="utf-8") if config.com_cnefe else "",
        )
        .replace("{secao_exemplos}", EXEMPLOS.read_text(encoding="utf-8"))
    )


def prompt_usuario(endereco: str, extras: str, n_rodadas: int) -> str:
    return f"""Extra info (context only; it does NOT populate segments):
{extras}

Raw address:
{endereco}

You have {n_rodadas} rounds.
"""


def segmentar(
    agente: Agente,
    endereco: str,
    extras: str = "",
    *,
    n_iter: int = 10,
    tolerancia_erro: int = 2,
) -> Resposta:
    """Roda o loop reAct ate obter uma segmentacao valida."""
    console = agente.console
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": prompt_sistema(agente.config)},
        {"role": "user", "content": prompt_usuario(endereco, extras, n_iter)},
    ]
    erros_consecutivos = 0

    for i in range(n_iter):
        console.rule(f"Iteração {i + 1}/{n_iter}")

        message = _requisitar(agente, messages)
        messages.append(message)
        if raciocinio := message.get("reasoning"):
            console.print(str(raciocinio), style="dim italic")
        if conteudo := message.get("content"):
            console.print(str(conteudo))

        chamadas = _chamadas(message)
        final = next((c for c in chamadas if c.nome == "responder"), None)
        if final is not None:
            resposta = _resposta_final(final)
            console.print(_visualizacao(endereco, resposta))
            problemas = _problemas(endereco, resposta)
            if not problemas:
                return resposta

            erros_consecutivos += 1
            if erros_consecutivos > tolerancia_erro:
                raise ErroSegmentacao(
                    f"Validação falhou {erros_consecutivos} vezes seguidas:\n"
                    + "\n".join(problemas)
                )
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "An error occurred while validating your segmentation. "
                        "Fix it and submit again.\n" + "\n".join(problemas)
                    ),
                }
            )
            continue

        for chamada in chamadas:
            console.print(f"[bold]{chamada.nome}[/bold] {chamada.argumentos}")
            saida = agente.ferramentas.despachar(chamada.nome, chamada.argumentos)
            console.print(saida)
            messages.append(
                {"role": "tool", "tool_call_id": chamada.id, "content": saida}
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


def _requisitar(agente: Agente, messages: list[dict[str, Any]]) -> dict[str, Any]:
    """Envia a conversa e devolve a `message` da primeira escolha."""
    corpo = agente.cliente.enviar_json(
        agente.config.url_chat,
        {
            "model": agente.config.api_model,
            "messages": messages,
            "tools": criar_ferramentas(agente.config),
            "temperature": 0.3,
        },
        headers={
            "Authorization": f"Bearer {agente.config.api_key}",
            "Content-Type": "application/json",
        },
    )
    escolhas = corpo.get("choices") or [{}]
    return dict(escolhas[0].get("message") or {})


def _chamadas(message: dict[str, Any]) -> list[Chamada]:
    """Tool calls da mensagem (argumentos em JSON malformado sao descartados)."""
    chamadas: list[Chamada] = []
    for call in message.get("tool_calls") or []:
        funcao = call.get("function") or {}
        try:
            argumentos = json.loads(funcao.get("arguments") or "{}")
        except (json.JSONDecodeError, TypeError):
            continue
        chamadas.append(
            Chamada(
                id=str(call.get("id", "")),
                nome=str(funcao.get("name", "")),
                argumentos=dict(argumentos),
            )
        )
    return chamadas


def _resposta_final(chamada: Chamada) -> Resposta:
    """Converte a chamada `responder` na resposta final estruturada."""
    segmentos = [
        Segmento(valor=str(seg.get("valor", "")), tipo=str(seg.get("tipo", "")))
        for seg in chamada.argumentos.get("segmentos", [])
    ]
    return Resposta(
        segmentos=segmentos, comentario=chamada.argumentos.get("comentario")
    )


def _problemas(endereco: str, resposta: Resposta) -> list[str]:
    """Segmentos que nao sao trechos verbatim e em ordem do endereco."""
    ultima_pos = 0
    problemas: list[str] = []
    for i, seg in enumerate(resposta.segmentos):
        posicao = endereco.find(seg.valor, ultima_pos)
        if posicao == -1:
            problemas.append(
                f"Could not locate segment #{i + 1}: {seg.valor} ({seg.tipo})"
            )
            continue
        ultima_pos = posicao + len(seg.valor)
    return problemas


def _visualizacao(endereco: str, resposta: Resposta) -> str:
    """Endereco com cada segmento anotado ao lado do seu tipo."""
    ultima_pos = 0
    partes: list[str] = []
    for seg in resposta.segmentos:
        posicao = endereco.find(seg.valor, ultima_pos)
        if posicao == -1:
            continue
        if posicao != ultima_pos:
            partes.append(endereco[ultima_pos:posicao])
        fim = posicao + len(seg.valor)
        partes.append(f"{endereco[posicao:fim]} [{seg.tipo}]")
        ultima_pos = fim
    if ultima_pos != len(endereco):
        partes.append(endereco[ultima_pos:])
    return "\n".join(partes)
