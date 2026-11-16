"""Agente que segmenta um endereco: prompt, ferramentas e loop reAct."""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Sequence
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
class Pedido:
    """Um dos enderecos de um lote: o texto e o contexto que a LLM ve dele."""

    endereco: str
    extras: str = ""


@dataclass(frozen=True)
class Resultado:
    """O que o lote rendeu: a resposta valida de cada indice e a falha de cada resto."""

    aceitas: dict[int, Resposta]
    falhas: dict[int, str]


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


def prompt_usuario(pedidos: Sequence[Pedido], n_rodadas: int) -> str:
    """Um bloco numerado por endereco: o numero e o `indice` da resposta."""
    blocos = "\n\n".join(
        f"""[{i}]
Extra info (context only; it does NOT populate segments):
{pedido.extras or "(none)"}

Raw address:
{pedido.endereco}"""
        for i, pedido in enumerate(pedidos, start=1)
    )
    return f"""{len(pedidos)} address(es) to segment.

{blocos}

Answer all of them in one `responder` call: one entry per bracket number, `indice` set to that number.
You have {n_rodadas} rounds.
"""


def segmentar(
    agente: Agente,
    pedidos: Sequence[Pedido],
    *,
    n_iter: int = 10,
    tolerancia_erro: int = 2,
) -> Resultado:
    """Roda o loop reAct ate cada pedido do lote ter uma segmentacao valida.

    A conversa e uma so: o pedido de sistema e as ferramentas sao amortizados
    entre todos os enderecos do lote. A validacao, porem, e por indice — o
    endereco que sai errado volta sozinho para a LLM, e o que ja estava certo
    nao e pedido de novo.
    """
    console = agente.console
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": prompt_sistema(agente.config)},
        {"role": "user", "content": prompt_usuario(pedidos, n_iter)},
    ]
    aceitas: dict[int, Resposta] = {}
    problemas: dict[int, list[str]] = {}
    falhas: dict[int, str] = {}
    erros_seguidos: Counter[int] = Counter()
    pendentes = list(range(len(pedidos)))

    console.print(f"\nLote de {len(pedidos)} endereco(s):\n", style="blue")
    for i, pedido in enumerate(pedidos, start=1):
        console.print(f"  [{i}] {pedido.endereco}", style="blue")

    for rodada in range(n_iter):
        console.rule(f"Iteração {rodada + 1}/{n_iter}")

        message = _requisitar(agente, messages)
        messages.append(message)
        if raciocinio := message.get("reasoning"):
            console.print(str(raciocinio), style="dim italic")
        if conteudo := message.get("content"):
            console.print(str(conteudo))

        chamadas = _chamadas(message)
        final = next((c for c in chamadas if c.nome == "responder"), None)
        if final is not None:
            for indice, resposta in _respostas(final, len(pedidos)).items():
                if indice in aceitas:
                    continue
                problemas_do_indice = _problemas(pedidos[indice].endereco, resposta)
                if problemas_do_indice:
                    problemas[indice] = problemas_do_indice
                    erros_seguidos[indice] += 1
                    continue
                console.print(_visualizacao(pedidos[indice].endereco, resposta))
                aceitas[indice] = resposta
                problemas.pop(indice, None)

            for indice in pendentes:
                if indice in aceitas:
                    continue
                if erros_seguidos[indice] > tolerancia_erro:
                    falhas[indice] = (
                        f"validacao falhou {erros_seguidos[indice]} vezes: "
                        + "; ".join(problemas.get(indice, []))
                    )
            pendentes = [
                indice
                for indice in pendentes
                if indice not in aceitas and indice not in falhas
            ]
            if not pendentes:
                return Resultado(aceitas, falhas)

            messages.append(
                {
                    "role": "user",
                    "content": _correcao(pedidos, pendentes, problemas),
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

        if rodada == n_iter - 1:
            console.print("[bold red]Última iteração[/bold red]")
            messages.append(
                {
                    "role": "user",
                    "content": "Final round - Give your answers now or abstain",
                }
            )

    for indice in pendentes:
        falhas.setdefault(indice, f"sem resposta final apos {n_iter} iteracoes")
    return Resultado(aceitas, falhas)


def _correcao(
    pedidos: Sequence[Pedido],
    pendentes: Sequence[int],
    problemas: dict[int, list[str]],
) -> str:
    """Pede de volta so os indices que faltam ou nao passaram na validacao."""
    linhas = [
        f"[{i + 1}] {pedidos[i].endereco}\n"
        + ("\n".join(problemas[i]) if i in problemas else "No answer yet.")
        for i in pendentes
    ]
    return (
        "These addresses still lack a valid answer. Fix them and submit again "
        "with `responder` (same `indice`):\n" + "\n".join(linhas)
    )


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


def _segmentos(argumentos: dict[str, Any]) -> list[Segmento]:
    """Normaliza `segmentos` quando o backend manda a lista como string JSON."""
    bruto = argumentos.get("segmentos") or []
    if isinstance(bruto, str):
        try:
            bruto = json.loads(bruto)
        except json.JSONDecodeError:
            return []
    if not isinstance(bruto, list):
        return []
    return [
        Segmento(valor=str(seg.get("valor", "")), tipo=str(seg.get("tipo", "")))
        for seg in bruto
        if isinstance(seg, dict)
    ]


def _respostas(chamada: Chamada, total: int) -> dict[int, Resposta]:
    """Converte a chamada `responder` nas respostas, por indice de pedido (0-based).

    Indice fora do lote e repetido ficam de fora: o que vale e a primeira
    resposta de cada endereco, e o que faltar volta no pedido de correcao.
    """
    bruto = chamada.argumentos.get("respostas") or []
    if isinstance(bruto, str):
        try:
            bruto = json.loads(bruto)
        except json.JSONDecodeError:
            return {}
    if not isinstance(bruto, list):
        return {}

    respostas: dict[int, Resposta] = {}
    for item in bruto:
        if not isinstance(item, dict):
            continue
        try:
            indice = int(item.get("indice", 0)) - 1
        except (TypeError, ValueError):
            continue
        if not 0 <= indice < total or indice in respostas:
            continue
        respostas[indice] = Resposta(
            segmentos=_segmentos(item), comentario=item.get("comentario")
        )
    return respostas


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
