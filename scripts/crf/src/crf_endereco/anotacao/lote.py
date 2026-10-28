"""Processamento de um lote de enderecos pendentes."""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass

from rich.console import Console

from crf_endereco.anotacao.agente import Agente, criar_agente, fechar_agente, segmentar
from crf_endereco.anotacao.pendentes import Pendente
from crf_endereco.config import Config
from crf_endereco.dataset import gravar_resposta, serializar_erro, serializar_sucesso
from crf_endereco.ui import progresso


@dataclass(frozen=True)
class Opcoes:
    """Parametros do loop reAct e do paralelismo de uma execucao em lote."""

    iteracoes: int
    tolerancia_erro: int
    concorrencia: int


@dataclass
class Resumo:
    """Contagem final de uma execucao em lote."""

    total: int = 0
    sucesso: int = 0
    erro: int = 0


def dividir_filtros(valores: list[str] | None) -> list[str]:
    """Divide valores repetidos/CSV de uma opcao numa lista limpa (pode ser vazia)."""
    itens = [item.strip() for valor in valores or () for item in valor.split(",")]
    return [item for item in itens if item]


def processar_linha(
    obter_agente: Callable[[], Agente], linha: Pendente, opcoes: Opcoes
) -> tuple[Pendente, str, bool]:
    """Segmenta uma linha; falha de segmentacao vira `{"erro": ...}`.

    A criacao do agente fica fora do `try`: um erro de ambiente (ex.: CNEFE
    inacessivel) deve abortar o lote, nao marcar cada linha como erro.
    """
    agente = obter_agente()
    try:
        resposta = segmentar(
            agente,
            linha.endereco,
            linha.extras,
            n_iter=opcoes.iteracoes,
            tolerancia_erro=opcoes.tolerancia_erro,
        )
    except Exception as erro:  # noqa: BLE001 — a falha e o resultado da linha
        return linha, serializar_erro(f"{type(erro).__name__}: {erro}"), False
    segmentos = [asdict(segmento) for segmento in resposta.segmentos]
    return linha, serializar_sucesso(segmentos, resposta.comentario), True


def executar_lote(
    conn: sqlite3.Connection,
    config: Config,
    linhas: list[Pendente],
    opcoes: Opcoes,
    *,
    console_llm: Console,
) -> Resumo:
    """Processa as linhas (sequencial ou paralelo) e grava cada resposta.

    Cada thread de trabalho tem o seu agente: a conexao DuckDB das ferramentas
    nao e thread-safe. Os workers so produzem resultado; a escrita no SQLite
    acontece na thread principal, a medida que os futuros completam.
    """
    locais = threading.local()
    criados: list[Agente] = []

    def obter_agente() -> Agente:
        agente: Agente | None = getattr(locais, "agente", None)
        if agente is None:
            agente = criar_agente(config, console_llm)
            locais.agente = agente
            criados.append(agente)  # append e atomico no CPython
        return agente

    resumo = Resumo(total=len(linhas))
    pool = ThreadPoolExecutor(max_workers=opcoes.concorrencia)
    try:
        with progresso(stderr=True) as barra:
            tarefa = barra.add_task("Etiquetando", total=len(linhas))
            futuros = [
                pool.submit(processar_linha, obter_agente, linha, opcoes)
                for linha in linhas
            ]
            for futuro in as_completed(futuros):
                linha, resposta_json, sucesso = futuro.result()
                gravar_resposta(conn, linha.id, resposta_json, config.api_model)
                if sucesso:
                    resumo.sucesso += 1
                else:
                    resumo.erro += 1
                barra.advance(tarefa)
    finally:
        pool.shutdown(wait=True, cancel_futures=True)
        for agente in criados:
            fechar_agente(agente)

    return resumo
