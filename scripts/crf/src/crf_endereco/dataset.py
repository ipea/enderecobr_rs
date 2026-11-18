"""Leitura e escrita do dataset anotado (SQLite)."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

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
    municipio: str = ""


@dataclass(frozen=True)
class Detalhe:
    """Uma linha do dataset com tudo o que o `explorar` precisa ver junto.

    `segmentos` e o alvo atual (vazio quando a linha nunca foi etiquetada) e
    `revisoes` guarda cada resposta trocada, da mais antiga para a mais nova:
    juntos, sao o historico do rotulo que o modelo aprendeu.
    """

    id: int
    endereco: str
    extras: str
    uf: str
    municipio: str
    origem: str
    lote: str
    recorte: str
    llm: str | None
    segmentos: tuple[dict[str, str], ...]
    comentario: str | None
    erro: str | None
    revisoes: tuple[dict[str, Any], ...]
    revisado_por: str | None


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
            llm TEXT,
            recorte TEXT NOT NULL DEFAULT ''
        );
        """
    )
    # Bancos criados antes da coluna `recorte`: sem ela nao ha como saber o que
    # o tagger viu.
    garantir_recorte(conn)


def garantir_recorte(conn: sqlite3.Connection) -> None:
    """Adiciona a coluna `recorte` num banco criado antes dela."""
    colunas = {linha[1] for linha in conn.execute("PRAGMA table_info(enderecos)")}
    if "recorte" not in colunas:
        _ = conn.execute(
            "ALTER TABLE enderecos ADD COLUMN recorte TEXT NOT NULL DEFAULT ''"
        )
    conn.commit()


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
    *,
    revisado_por: str | None = None,
) -> None:
    """Grava o resultado de uma linha e commita (progresso persistido).

    Com `revisado_por`, a resposta que esta sendo trocada vai para
    `meta.revisoes` e o modelo fica marcado em `meta.revisado.modelo`:
    reetiquetar apaga o rotulo que treinou o modelo, e sem esse rastro nao daria
    nem para auditar a troca nem para saber que a linha ja foi revista.
    """
    agora = datetime.now(UTC).isoformat()
    if revisado_por is None:
        _ = conn.execute(
            """
            UPDATE enderecos
            SET resposta_llm = ?, data_processamento = ?, llm = ?
            WHERE id = ?
            """,
            (resposta_llm, agora, llm, id_linha),
        )
        conn.commit()
        return

    # No UPDATE o lado direito le a linha antiga: `resposta_llm`,
    # `data_processamento` e `llm` aqui sao os da anotacao sendo substituida.
    _ = conn.execute(
        """
        UPDATE enderecos
        SET resposta_llm = ?, data_processamento = ?, llm = ?,
            meta = json_set(
                meta,
                '$.revisoes',
                json_insert(
                    coalesce(json_extract(meta, '$.revisoes'), json_array()),
                    '$[#]',
                    json_object(
                        'data', data_processamento,
                        'llm', llm,
                        'resposta', json(resposta_llm)
                    )
                ),
                '$.revisado',
                json_object('modelo', ?, 'data', ?)
            )
        WHERE id = ?
        """,
        (resposta_llm, agora, llm, revisado_por, agora, id_linha),
    )
    conn.commit()


def gravar_recorte(
    conn: sqlite3.Connection,
    modelo: str,
    treino: Iterable[str],
    teste: Iterable[str],
) -> None:
    """Marca no banco o papel de cada endereco no recorte de um modelo.

    E o que permite `avaliar` medir no que o modelo nunca viu: o split deixa de
    ser presumido a partir das opcoes de linha de comando.
    """
    garantir_recorte(conn)
    for papel, hashes in (("treino", treino), ("teste", teste)):
        _ = conn.executemany(
            "UPDATE enderecos SET recorte = ? WHERE hash_endereco = ?",
            [(f"{modelo}/{papel}", hash_) for hash_ in hashes],
        )
    conn.commit()


def ler_recorte(conn: sqlite3.Connection, modelo: str) -> dict[str, set[str]]:
    """Hashes de treino e teste gravados para o modelo (vazios se nao houver)."""
    garantir_recorte(conn)
    recorte: dict[str, set[str]] = {}
    for papel in ("treino", "teste"):
        recorte[papel] = {
            str(linha[0])
            for linha in conn.execute(
                "SELECT hash_endereco FROM enderecos WHERE recorte = ?",
                (f"{modelo}/{papel}",),
            )
        }
    return recorte


def carregar_anotados(caminho: Path = CAMINHO_DATASET) -> list[Exemplo]:
    """Todos os enderecos com anotacao bem-sucedida (base do treino e da avaliacao)."""
    conn = abrir_banco(caminho)
    try:
        linhas = conn.execute(
            """
            SELECT endereco, resposta_llm, origem, uf,
                   coalesce(municipio, '') AS municipio
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
            municipio=str(linha["municipio"]),
        )
        for linha in linhas
    ]


def carregar_detalhes(
    conn: sqlite3.Connection, ids: Sequence[int]
) -> dict[int, Detalhe]:
    """Linhas do dataset por id, com resposta e historico de revisao decodificados."""
    if not ids:
        return {}
    linhas = conn.execute(
        """
        SELECT id, endereco, extras, coalesce(uf, '') AS uf,
               coalesce(municipio, '') AS municipio,
               coalesce(origem, '') AS origem, lote, recorte, llm,
               resposta_llm, meta
        FROM enderecos
        WHERE id IN (SELECT value FROM json_each(?))
        """,
        (json.dumps(sorted(ids)),),
    ).fetchall()

    detalhes: dict[int, Detalhe] = {}
    for linha in linhas:
        resposta = _decodificar(linha["resposta_llm"], "resposta")
        meta = _decodificar(linha["meta"], "meta")
        revisado = meta.get("revisado") or {}
        detalhes[int(linha["id"])] = Detalhe(
            id=int(linha["id"]),
            endereco=str(linha["endereco"]),
            extras=str(linha["extras"]),
            uf=str(linha["uf"]),
            municipio=str(linha["municipio"]),
            origem=str(linha["origem"]),
            lote=str(linha["lote"]),
            recorte=str(linha["recorte"]),
            llm=linha["llm"],
            segmentos=tuple(
                cast("list[dict[str, str]]", resposta.get("segmentos")) or ()
            ),
            comentario=resposta.get("comentario"),
            erro=resposta.get("erro"),
            revisoes=tuple(cast("list[dict[str, Any]]", meta.get("revisoes")) or ()),
            revisado_por=revisado.get("modelo"),
        )
    return detalhes


def _decodificar(texto: str | None, rotulo: str) -> dict[str, Any]:
    """JSON de uma coluna (`{}` quando a linha nao tem valor).

    Invalido vira erro explicito: mostrar a linha como se nao tivesse resposta
    esconderia um banco corrompido.
    """
    if not texto:
        return {}
    try:
        dados = json.loads(texto)
    except json.JSONDecodeError as erro:
        raise RuntimeError(f"{rotulo} inválida no banco: {erro}") from erro
    if not isinstance(dados, dict):
        raise TypeError(f"{rotulo} do banco não é um objeto JSON: {texto[:60]!r}")
    return dados


def segmentos_de(exemplo: Exemplo) -> list[dict[str, str]]:
    """Segmentos da resposta da LLM (JSON invalido vira erro explicito)."""
    try:
        resposta = json.loads(exemplo.resposta)
    except json.JSONDecodeError as erro:
        raise RuntimeError(
            f"Resposta inválida no endereço {exemplo.endereco!r}: {erro}"
        ) from erro
    return list(resposta.get("segmentos", []))
