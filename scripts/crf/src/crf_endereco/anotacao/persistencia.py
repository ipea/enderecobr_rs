"""Leitura e escrita do dataset anotado (SQLite)."""

import hashlib
import json
import sqlite3
import time
from collections.abc import Iterable
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

import typer

from crf_endereco.anotacao.estratificacao import LinhaPendente
from crf_endereco.anotacao.populacao.populador import (
    RegistroEtiquetacao,
    normalizar_municipio,
    normalizar_uf,
)
from crf_endereco.anotacao.resposta import RespostaFinal


def criar_banco(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS enderecos (
            id INTEGER PRIMARY KEY,
            endereco TEXT NOT NULL,
            extras TEXT NOT NULL DEFAULT '',
            meta TEXT NOT NULL DEFAULT '{}',
            resposta_llm TEXT,
            origem TEXT NOT NULL,
            origem_id TEXT,
            municipio TEXT,
            uf TEXT,
            lote TEXT NOT NULL,
            hash_endereco TEXT NOT NULL UNIQUE,
            data_criacao TEXT NOT NULL,
            data_processamento TEXT,
            llm TEXT
        );
        """
    )

def contar_registros(conn: sqlite3.Connection) -> int:
    linha = conn.execute("SELECT count(*) FROM enderecos").fetchone()
    return int(linha[0])

def ler_enderecos_existentes(conn: sqlite3.Connection) -> list[str]:
    return [linha[0] for linha in conn.execute("SELECT endereco FROM enderecos")]

def calcular_hash(endereco: str) -> str:
    return hashlib.sha256(endereco.encode("utf-8")).hexdigest()

def gravar_registros(
    conn: sqlite3.Connection,
    registros: Iterable[RegistroEtiquetacao],
    lote: str,
) -> tuple[int, int]:
    """Insere ignorando hashes já presentes. Retorna (inseridos, ignorados)."""
    agora = datetime.now(UTC).isoformat()
    # `id` é a unix epoch em nanossegundos (offset por índice evita colisão
    # quando duas linhas caem no mesmo nanossegundo).
    base_ns = time.time_ns()
    antes = conn.total_changes
    total = 0
    for i, r in enumerate(registros):
        conn.execute(
            """
            INSERT OR IGNORE INTO enderecos
                (id, endereco, extras, meta, origem, origem_id, municipio, uf,
                 lote, hash_endereco, data_criacao)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                base_ns + i,
                r.endereco,
                r.extras,
                json.dumps(r.meta, ensure_ascii=False),
                r.origem,
                r.origem_id,
                normalizar_municipio(r.municipio),
                normalizar_uf(r.uf),
                lote,
                calcular_hash(r.endereco),
                agora,
            ),
        )
        total += 1
    conn.commit()
    inseridos = conn.total_changes - antes
    return inseridos, total - inseridos

def montar_lote(tipo_dataset: str) -> str:
    return f"{tipo_dataset}-{datetime.now(UTC):%Y%m%dT%H%M%S}"

def abrir_banco(caminho: Path) -> sqlite3.Connection:
    """Abre o SQLite gerado por `dataset_etiquetacao.py`."""
    if not caminho.is_file():
        raise typer.BadParameter(f"Banco de dados não encontrado: {caminho}")
    conn = sqlite3.connect(str(caminho))
    conn.row_factory = sqlite3.Row
    return conn

def serializar_sucesso(resultado: RespostaFinal) -> str:
    """Serializa a segmentação da LLM (o valor gravado em `resposta_llm`)."""
    return json.dumps(
        {
            "segmentos": [asdict(segmento) for segmento in resultado.segmentos],
            "comentario": resultado.comentario,
        },
        ensure_ascii=False,
    )

def serializar_erro(mensagem: str) -> str:
    """Marca a linha como falha (recuperável via `--retentar-erros`)."""
    return json.dumps({"erro": mensagem}, ensure_ascii=False)

def gravar_resposta(
    conn: sqlite3.Connection,
    linha: LinhaPendente,
    resposta_llm: str,
    llm: str,
) -> None:
    """Grava o resultado de uma linha e commita (progresso persistido)."""
    _ = conn.execute(
        """
        UPDATE enderecos
        SET resposta_llm = ?, data_processamento = ?, llm = ?
        WHERE id = ?
        """,
        (resposta_llm, datetime.now(UTC).isoformat(), llm, linha.id),
    )
    conn.commit()
