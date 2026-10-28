"""Processamento de um lote de enderecos pendentes."""

from __future__ import annotations

import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass

from rich.console import Console

from crf_endereco.anotacao.estratificacao import LinhaPendente
from crf_endereco.anotacao.segmentacao import Contexto, segmentar
from crf_endereco.config import Config
from crf_endereco.dataset import (
    gravar_resposta,
    serializar_erro,
    serializar_sucesso,
)
from crf_endereco.ui import progresso


@dataclass(frozen=True)
class OpcoesLote:
    """Parâmetros do loop reAct e do paralelismo de uma execução em lote."""

    iteracoes: int
    tolerancia_erro: int
    concorrencia: int


class FabricaContextos:
    """Cria um `Contexto` por thread de trabalho.

    `Contexto` abre uma conexão DuckDB, que não é thread-safe; uma instância
    por worker evita compartilhar conexão entre threads.
    """

    def __init__(self, config: Config, console: Console) -> None:
        self.config: Config = config
        self.console: Console = console
        self._local: threading.local = threading.local()
        self._criados: list[Contexto] = []
        self._lock: threading.Lock = threading.Lock()

    def obter(self) -> Contexto:
        contexto: Contexto | None = getattr(self._local, "contexto", None)
        if contexto is None:
            contexto = Contexto.criar(self.config, self.console)
            self._local.contexto = contexto
            with self._lock:
                self._criados.append(contexto)
        return contexto

    def fechar(self) -> None:
        with self._lock:
            criados, self._criados = self._criados, []
        for contexto in criados:
            contexto.fechar()


def processar_linha(
    fabrica: FabricaContextos, linha: LinhaPendente, opcoes: OpcoesLote
) -> tuple[LinhaPendente, str, bool]:
    """Segmenta uma linha; falha de segmentação vira `{"erro": ...}`.

    A criação do contexto fica fora do `try`: um erro de ambiente (ex.: CNEFE
    inacessível) deve abortar o lote, não marcar cada linha como erro.
    """
    contexto = fabrica.obter()
    try:
        resultado = segmentar(
            contexto,
            linha.endereco,
            linha.extras,
            n_iter=opcoes.iteracoes,
            tolerancia_erro=opcoes.tolerancia_erro,
        )
    except Exception as e:  # noqa: BLE001 — a falha é o resultado da linha
        return linha, serializar_erro(f"{type(e).__name__}: {e}"), False
    segmentos = [asdict(segmento) for segmento in resultado.segmentos]
    return linha, serializar_sucesso(segmentos, resultado.comentario), True


@dataclass
class ResumoLote:
    """Contagem final de uma execução em lote."""

    total: int = 0
    sucesso: int = 0
    erro: int = 0


def executar_lote(
    conn: sqlite3.Connection,
    config: Config,
    linhas: list[LinhaPendente],
    opcoes: OpcoesLote,
    *,
    console_llm: Console,
) -> ResumoLote:
    """Processa as linhas (sequencial ou paralelo) e grava cada resposta.

    Os workers só produzem resultado; a escrita no SQLite acontece na thread
    principal, à medida que os futuros completam.
    """
    fabrica = FabricaContextos(config, console_llm)
    resumo = ResumoLote(total=len(linhas))

    pool = ThreadPoolExecutor(max_workers=opcoes.concorrencia)
    try:
        with progresso(stderr=True) as barra:
            tarefa = barra.add_task("Etiquetando", total=len(linhas))
            futuros = [
                pool.submit(processar_linha, fabrica, linha, opcoes) for linha in linhas
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
        fabrica.fechar()

    return resumo


def _dividir_filtros(valores: list[str] | None) -> list[str] | None:
    """Divide valores repetidos/CSV de uma opção em uma lista limpa (ou None)."""
    if not valores:
        return None
    itens = [item.strip() for valor in valores for item in valor.split(",")]
    limpos = [item for item in itens if item]
    return limpos or None
