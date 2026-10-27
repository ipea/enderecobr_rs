"""Filtro de pendentes pelas categorias que o CRF preve."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import cast

import typer
from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    TextColumn,
    TimeElapsedColumn,
)

from crf_endereco.anotacao.estratificacao import LinhaPendente
from crf_endereco.anotacao.ontologia import TIPOS_SEGMENTO
from crf_endereco.segmentador_rust import rodar_segmentacao

# Rótulos que o CRF consegue emitir: espelham `TipoSegmento::TODOS` do Rust.
# Ficam de fora `cadastro`, `ruido` e `outros`: `treinamento.mapa_tipo_segmento`
# os colapsa em `O`, então o modelo nunca os prevê (`outros` só aparece como
# fallback de rótulo desconhecido no Rust).
TIPOS_SEGMENTO_CRF = frozenset(
    {
        "logradouro",
        "logradouro_interno",
        "numero",
        "modificador_numero",
        "complemento",
        "empreendimento",
        "parcela",
        "descricao_area",
        "quilometragem_via",
        "referencia",
        "denominacao",
        "localidade",
        "cep",
        "municipio",
        "uf",
    }
)

# Quantos endereços vão por chamada ao segmentador (uma linha de entrada e uma
# de saída JSON por endereço).
TAMANHO_BLOCO_CRF = 5_000

def garantir_tabela_filtro(conn: sqlite3.Connection) -> None:
    """Cria a tabela temporária `_filtro_crf` usada pelas consultas de lote.

    É idempotente e precisa existir mesmo quando o filtro está desligado, porque
    as consultas de pendentes a citam em um `IN` com parâmetro de desligamento.
    """
    _ = conn.execute(
        "CREATE TEMP TABLE IF NOT EXISTS _filtro_crf (id INTEGER PRIMARY KEY)"
    )

def registrar_filtro_crf(conn: sqlite3.Connection, ids: Iterable[int]) -> None:
    """Grava em `_filtro_crf` os ids que passaram pelo filtro do modelo."""
    garantir_tabela_filtro(conn)
    _ = conn.execute("DELETE FROM _filtro_crf")
    _ = conn.executemany(
        "INSERT OR IGNORE INTO _filtro_crf (id) VALUES (?)",
        [(identificador,) for identificador in ids],
    )
    conn.commit()

def contar_filtro_crf(conn: sqlite3.Connection) -> int:
    """Quantos ids passaram pelo filtro do modelo na conexão."""
    garantir_tabela_filtro(conn)
    linha = conn.execute("SELECT count(*) FROM _filtro_crf").fetchone()
    return cast(int, linha[0]) if linha is not None else 0

def validar_tipos_filtro(
    valores: list[str] | None, modelo: Path | None
) -> frozenset[str]:
    """Normaliza e valida a lista de `--apenas-tipos`; vazia = filtro desligado.

    Erra com mensagem explícita quando o tipo não existe na ontologia ou quando
    existe mas o CRF nunca o emite (`cadastro`, `ruido`, `outros` são colapsados
    em `O` pelo treinamento).
    """
    if modelo is not None and not modelo.is_file():
        raise typer.BadParameter(f"Modelo CRF não encontrado: {modelo}")
    if not valores:
        return frozenset()

    tipos = frozenset(item.strip().lower() for item in valores if item.strip())
    desconhecidos = sorted(tipos - set(TIPOS_SEGMENTO))
    if desconhecidos:
        raise typer.BadParameter(
            f"Tipo(s) desconhecido(s): {', '.join(desconhecidos)}. "
            f"Válidos: {', '.join(sorted(TIPOS_SEGMENTO))}."
        )
    sem_modelo = sorted(tipos - TIPOS_SEGMENTO_CRF)
    if sem_modelo:
        raise typer.BadParameter(
            f"O CRF não prevê {', '.join(sem_modelo)}: o treinamento colapsa "
            "esses rótulos em `O`. Use um tipo que o modelo emite."
        )
    return tipos

def filtrar_ids_por_tipos(
    saida: Sequence[str], ids: Sequence[int], tipos: frozenset[str]
) -> set[int]:
    """Ids cuja segmentação (um JSON por linha) tem ao menos um segmento de `tipos`.

    Linha ilegível conta como não selecionada: o filtro só inclui quem o modelo
    comprovadamente marcou com um dos tipos pedidos.
    """
    selecionados: set[int] = set()
    for identificador, linha in zip(ids, saida, strict=True):
        try:
            dados = json.loads(linha)
        except json.JSONDecodeError:
            continue
        for segmento in dados.get("segmentos", []):
            if str(segmento.get("tipo", "")) in tipos:
                selecionados.add(identificador)
                break
    return selecionados

def prever_tipos_crf(
    linhas: Sequence[LinhaPendente],
    tipos: frozenset[str],
    modelo: Path | None,
    binario: Path | None,
    console: Console,
) -> set[int]:
    """Roda o CRF nos pendentes e devolve os ids com ao menos um dos `tipos`.

    Usa o binário do próprio enderecobr_rs, então a predição é idêntica à do
    segmentador publicado; o modelo é escolhido por `--modelo-crf`
    (`ENDERECOBR_MODELO` para o binário) ou pelo padrão dele.
    """
    selecionados: set[int] = set()
    progresso = Progress(
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        console=console,
    )
    with progresso:
        tarefa = progresso.add_task("Prevendo com o CRF", total=len(linhas))
        for inicio in range(0, len(linhas), TAMANHO_BLOCO_CRF):
            bloco = linhas[inicio : inicio + TAMANHO_BLOCO_CRF]
            saida = rodar_segmentacao(
                [linha.endereco for linha in bloco], modelo=modelo, binario=binario
            )
            selecionados |= filtrar_ids_por_tipos(
                saida, [linha.id for linha in bloco], tipos
            )
            progresso.advance(tarefa, len(bloco))
    return selecionados


