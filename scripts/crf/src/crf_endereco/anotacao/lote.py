"""Processamento de um lote de enderecos pendentes."""

from __future__ import annotations

import os
import signal
import sqlite3
import threading
from collections import deque
from collections.abc import Callable, Sequence
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import asdict, dataclass

from rich.console import Console

from crf_endereco.anotacao.agente import (
    Agente,
    Pedido,
    criar_agente,
    fechar_agente,
    segmentar,
)
from crf_endereco.anotacao.pendentes import Pendente
from crf_endereco.config import Config
from crf_endereco.dataset import gravar_resposta, serializar_erro, serializar_sucesso
from crf_endereco.ui import console as console_padrao
from crf_endereco.ui import progresso

# Uma resposta por linha do banco: (id da linha, JSON gravado, se deu certo).
Gravacao = tuple[int, str, bool]


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
    interrompido: bool = False


def dividir_filtros(valores: list[str] | None) -> list[str]:
    """Divide valores repetidos/CSV de uma opcao numa lista limpa (pode ser vazia)."""
    itens = [item.strip() for valor in valores or () for item in valor.split(",")]
    return [item for item in itens if item]


def _empacotar(
    linhas: Sequence[Pendente], nivel: int, tamanho: int
) -> tuple[list[list[Pendente]], list[list[Pendente]]]:
    """Grupos cheios e sobras, por chave das `nivel` primeiras colunas da celula.

    Os cheios saem na ordem em que fecham, que e a ordem do sorteio.
    """
    cheios: list[list[Pendente]] = []
    abertos: dict[tuple[str, ...], list[Pendente]] = {}
    for linha in linhas:
        chave = (linha.uf, linha.municipio, linha.origem)[:nivel]
        grupo = abertos.setdefault(chave, [])
        grupo.append(linha)
        if len(grupo) == tamanho:
            cheios.append(abertos.pop(chave))
    return cheios, [grupo for grupo in abertos.values() if grupo]


def agrupar(linhas: Sequence[Pendente], tamanho: int) -> list[list[Pendente]]:
    """Grupos de ate `tamanho` enderecos, da mesma celula enquanto ela enche.

    A mesma celula (uf, municipio, origem) e o que faz o lote render: as
    consultas ao CNEFE de um endereco servem para os vizinhos. O que sobra de
    uma celula tenta fechar com os vizinhos do municipio, qualquer origem — a
    consulta ao CNEFE continua valendo. Parar no municipio e proposital:
    misturar municipios desfaria o ganho, entao a sobra vira lote parcial.

    Os grupos cheios saem na ordem em que fecham, entao o balanceamento entre
    celulas do sorteio continua valendo; as sobras ficam para o fim.
    """
    if tamanho <= 1:
        return [[linha] for linha in linhas]

    cheios, sobras = _empacotar(linhas, 3, tamanho)
    do_municipio, parciais = _empacotar(
        [linha for grupo in sobras for linha in grupo], 2, tamanho
    )
    return cheios + do_municipio + parciais


def compor_lotes(
    linhas: Sequence[Pendente], tamanho: int, limite: int | None = None
) -> list[list[Pendente]]:
    """Lotes de ate `tamanho`, cortando em `limite` enderecos.

    O limite vale sobre enderecos, e nao sobre lotes: cortar antes de agrupar e
    o que deixava todo lote com um endereco so, porque a ordenacao dos pendentes
    intercala as celulas. O ultimo lote pode ficar menor que `tamanho`.
    """
    grupos = agrupar(linhas, tamanho)
    if limite is None:
        return grupos
    recorte: list[list[Pendente]] = []
    total = 0
    for grupo in grupos:
        if total >= limite:
            break
        recorte.append(grupo[: limite - total])
        total += len(recorte[-1])
    return recorte


def processar_grupo(
    obter_agente: Callable[[], Agente], grupo: Sequence[Pendente], opcoes: Opcoes
) -> list[Gravacao]:
    """Segmenta as linhas de um grupo numa conversa so; falha vira `{"erro": ...}`.

    A criacao do agente fica fora do `try`: um erro de ambiente (ex.: CNEFE
    inacessivel) deve abortar o lote, nao marcar cada linha como erro.
    """
    agente = obter_agente()
    pedidos = [Pedido(linha.endereco, linha.extras) for linha in grupo]
    try:
        resultado = segmentar(
            agente,
            pedidos,
            n_iter=opcoes.iteracoes,
            tolerancia_erro=opcoes.tolerancia_erro,
        )
    except Exception as erro:  # noqa: BLE001 — a falha e o resultado das linhas
        motivo = serializar_erro(f"{type(erro).__name__}: {erro}")
        return [(linha.id, motivo, False) for linha in grupo]

    gravacoes: list[Gravacao] = []
    for i, linha in enumerate(grupo):
        resposta = resultado.aceitas.get(i)
        if resposta is None:
            motivo = resultado.falhas.get(i, "sem resposta para este endereco")
            gravacoes.append((linha.id, serializar_erro(motivo), False))
            continue
        segmentos = [asdict(segmento) for segmento in resposta.segmentos]
        gravacoes.append(
            (linha.id, serializar_sucesso(segmentos, resposta.comentario), True)
        )
    return gravacoes


def gravar_gravacoes(
    conn: sqlite3.Connection,
    gravacoes: Sequence[Gravacao],
    llm: str,
    *,
    revisado_por: str | None = None,
) -> tuple[int, int]:
    """Grava as respostas de um grupo e conta (sucessos, erros).

    Numa revisao (`revisado_por`) a linha que falha nao e gravada: trocar um
    rotulo por `{"erro": ...}` so tiraria o exemplo do treino, e a proxima
    revisao a pega de novo.
    """
    sucessos = erros = 0
    for linha_id, resposta_json, sucesso in gravacoes:
        if not sucesso and revisado_por is not None:
            erros += 1
            continue
        gravar_resposta(conn, linha_id, resposta_json, llm, revisado_por=revisado_por)
        if sucesso:
            sucessos += 1
        else:
            erros += 1
    return sucessos, erros


def executar_lote(
    conn: sqlite3.Connection,
    config: Config,
    grupos: Sequence[Sequence[Pendente]],
    opcoes: Opcoes,
    *,
    console_llm: Console,
    revisado_por: str | None = None,
    ao_iniciar_lote: Callable[[int, int, Sequence[Pendente]], None] | None = None,
    ao_gravar_lote: (
        Callable[[int, int, Sequence[Pendente], Sequence[Gravacao]], None] | None
    ) = None,
) -> Resumo:
    """Processa os lotes (sequencial ou paralelo) e grava cada resposta.

    Cada thread de trabalho tem o seu agente: a conexao DuckDB das ferramentas
    nao e thread-safe. Os workers so produzem resultado; a escrita no SQLite
    acontece na thread principal, a medida que os futuros completam.

    `revisado_por` marca no banco que a linha foi reetiquetada (ver
    `gravar_resposta`): so o `--divergentes` passa um modelo, que ja tem uma
    anotacao e esta sendo trocada. Nesse modo a linha que falha nao e gravada:
    trocar um rotulo por `{"erro": ...}` so tiraria o exemplo do treino.

    `ao_iniciar_lote` e chamado na thread principal quando um lote sai da fila
    (numero, total de lotes, linhas), antes de a chamada a LLM comecar: e onde a
    dificuldade prevista de cada endereco aparece, no momento em que serve.
    `ao_gravar_lote` recebe o mesmo lote depois da gravacao, com as respostas —
    e onde da para comparar o rotulo antigo com o que a LLM acabou de dizer.

    Ctrl+C interrompe de forma ordenada: os lotes em voo terminam e sao
    gravados, e os que ainda nao comecaram nunca comecam. O segundo Ctrl+C mata
    o processo na hora.
    """
    locais = threading.local()
    criados: list[Agente] = []
    parar = threading.Event()

    def interromper(_sinal: int, _frame: object) -> None:
        if parar.is_set():
            # Segundo Ctrl+C. Sair pelo caminho normal nao basta: as threads do
            # pool nao sao daemon e o interpretador as espera no exit.
            signal.signal(signal.SIGINT, signal.SIG_DFL)
            console_padrao.print("\n[bold red]Abortado.[/bold red]")
            os._exit(130)
        parar.set()
        console_padrao.print(
            "\n[yellow]Ctrl+C: os lotes em voo terminam e são gravados. "
            "Ctrl+C de novo mata agora.[/yellow]"
        )

    def obter_agente() -> Agente:
        agente: Agente | None = getattr(locais, "agente", None)
        if agente is None:
            agente = criar_agente(config, console_llm)
            locais.agente = agente
            criados.append(agente)  # append e atomico no CPython
        return agente

    total = sum(len(grupo) for grupo in grupos)
    resumo = Resumo(total=total)
    # O lote fica junto do futuro: os callbacks precisam das linhas, nao so do id.
    em_voo: dict[Future[list[Gravacao]], tuple[int, Sequence[Pendente]]] = {}
    fila = deque(grupos)
    iniciados = 0
    pool = ThreadPoolExecutor(max_workers=opcoes.concorrencia)
    anterior = signal.signal(signal.SIGINT, interromper)
    try:
        with progresso(stderr=True) as barra:
            tarefa = barra.add_task("Etiquetando", total=total)
            while em_voo or fila:
                # Enfileirar so enquanto ha vaga e ninguem pediu para parar: e
                # o que deixa o Ctrl+C cortar sem cancelar nada (futuro
                # cancelado nao avisa quem espera por ele).
                while fila and len(em_voo) < opcoes.concorrencia and not parar.is_set():
                    grupo = fila.popleft()
                    iniciados += 1
                    if ao_iniciar_lote is not None:
                        ao_iniciar_lote(iniciados, len(grupos), grupo)
                    futuro = pool.submit(processar_grupo, obter_agente, grupo, opcoes)
                    em_voo[futuro] = (iniciados, grupo)
                if not em_voo:
                    break
                prontos, _ = wait(em_voo, return_when=FIRST_COMPLETED)
                for futuro in prontos:
                    numero, grupo = em_voo.pop(futuro)
                    gravacoes = futuro.result()
                    sucessos, erros = gravar_gravacoes(
                        conn, gravacoes, config.api_model, revisado_por=revisado_por
                    )
                    resumo.sucesso += sucessos
                    resumo.erro += erros
                    barra.advance(tarefa, len(gravacoes))
                    if ao_gravar_lote is not None:
                        ao_gravar_lote(numero, len(grupos), grupo, gravacoes)
    finally:
        signal.signal(signal.SIGINT, anterior)
        resumo.interrompido = parar.is_set()
        pool.shutdown(wait=True)
        for agente in criados:
            fechar_agente(agente)

    return resumo
