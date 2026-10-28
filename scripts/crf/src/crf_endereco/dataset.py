"""Leitura e escrita do dataset anotado (SQLite)."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import typer

from crf_endereco.config import CAMINHO_DATASET
from crf_endereco.registro import Registro


@dataclass(frozen=True)
class Exemplo:
    """Um endereco ja etiquetado com sucesso (sem `$.erro`)."""

    endereco: str
    resposta: str
    origem: str
    uf: str


@dataclass(frozen=True)
class Gravacao:
    """Resultado de uma insercao em lote."""

    inseridos: int
    ignorados: int
    lote: str


def abrir_banco(caminho: Path = CAMINHO_DATASET) -> sqlite3.Connection:
    """Abre o SQLite do dataset (erro claro quando o arquivo nao existe)."""
    if not caminho.is_file():
        raise typer.BadParameter(f"Banco de dados não encontrado: {caminho}")
    conn = sqlite3.connect(str(caminho))
    conn.row_factory = sqlite3.Row
    return conn


def criar_banco(conn: sqlite3.Connection) -> None:
    _ = conn.execute("PRAGMA journal_mode = WAL;")
    _ = conn.executescript(
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
    return int(linha[0]) if linha is not None else 0


def ler_enderecos_existentes(conn: sqlite3.Connection) -> list[str]:
    return [linha[0] for linha in conn.execute("SELECT endereco FROM enderecos")]


def calcular_hash(endereco: str) -> str:
    return hashlib.sha256(endereco.encode("utf-8")).hexdigest()


def montar_lote(tipo_dataset: str) -> str:
    return f"{tipo_dataset}-{datetime.now(UTC):%Y%m%dT%H%M%S}"


def gravar_registros(
    conn: sqlite3.Connection,
    registros: Iterable[Registro],
    lote: str,
) -> Gravacao:
    """Insere ignorando hashes ja presentes."""
    agora = datetime.now(UTC).isoformat()
    conn.commit()
    # `id` e a unix epoch em nanossegundos (offset por indice evita colisao
    # quando duas linhas caem no mesmo nanossegundo).
    base_ns = time.time_ns()
    antes = conn.total_changes
    total = 0
    for i, r in enumerate(registros):
        _ = conn.execute(
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
                r.municipio,
                r.uf,
                lote,
                calcular_hash(r.endereco),
                agora,
            ),
        )
        total += 1
    conn.commit()
    inseridos = conn.total_changes - antes
    return Gravacao(inseridos=inseridos, ignorados=total - inseridos, lote=lote)


def serializar_sucesso(segmentos: list[dict[str, str]], comentario: str | None) -> str:
    """Serializa a segmentacao da LLM (o valor gravado em `resposta_llm`)."""
    return json.dumps(
        {"segmentos": segmentos, "comentario": comentario}, ensure_ascii=False
    )


def serializar_erro(mensagem: str) -> str:
    """Marca a linha como falha (recuperavel via `--retentar-erros`)."""
    return json.dumps({"erro": mensagem}, ensure_ascii=False)


def gravar_resposta(
    conn: sqlite3.Connection,
    id_linha: int,
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
        (resposta_llm, datetime.now(UTC).isoformat(), llm, id_linha),
    )
    conn.commit()


def carregar_anotados(caminho: Path = CAMINHO_DATASET) -> list[Exemplo]:
    """Todos os enderecos com anotacao bem-sucedida (base do treino e da avaliacao)."""
    conn = abrir_banco(caminho)
    try:
        linhas = conn.execute(
            """
            SELECT endereco, resposta_llm, origem, uf
            FROM enderecos
            WHERE resposta_llm IS NOT NULL
              AND json_extract(resposta_llm, '$.erro') IS NULL
            """
        ).fetchall()
    finally:
        conn.close()
    return [
        Exemplo(
            endereco=str(linha["endereco"]),
            resposta=str(linha["resposta_llm"]),
            origem=str(linha["origem"] or ""),
            uf=str(linha["uf"] or ""),
        )
        for linha in linhas
    ]


def segmentos_de(exemplo: Exemplo) -> list[dict[str, str]]:
    """Segmentos da resposta da LLM (JSON invalido vira erro explicito)."""
    try:
        resposta = json.loads(exemplo.resposta)
    except json.JSONDecodeError as erro:
        raise RuntimeError(
            f"Resposta inválida no endereço {exemplo.endereco!r}: {erro}"
        ) from erro
    return list(resposta.get("segmentos", []))
