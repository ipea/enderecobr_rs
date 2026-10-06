#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "duckdb>=1.4.1",
#     "rapidfuzz",
#     "rich",
#     "tqdm",
#     "typer",
# ]
# ///
"""Popula o dataset inicial que será etiquetado pela LLM (`etiquetar.py`).

Cria/append um SQLite com um endereço bruto por linha, sua "extra info" e
metadados. Cada `tipo_dataset` chaveia um populador, que sabe ler a origem
(xlsx/csv/parquet) via DuckDB, montar `endereco`/`extras`/`meta`/`origem` e
sortear uma amostra.

Uso:
    uv run dataset_etiquetacao.py imoveis_uniao ORIGEM.xlsx destino.db -n 1000 --seed 42

Notas:
- A origem é lida com DuckDB (streaming, um único passe); o destino é
  escrito com `sqlite3` (append).
- O filtro de diversidade (`--similaridade-maxima`) usa rapidfuzz (escala
  0–100) contra os endereços já presentes no banco.
- A amostra é construída com reservoir sampling sobre o stream (memória
  constante, reprodutível via `--seed`): pede-se o tamanho exato e, havendo
  endereços diversos suficientes, a amostra sai cheia.
"""

from __future__ import annotations

import hashlib
import json
import random
import sqlite3
import time
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, ClassVar

import duckdb
import tqdm
import typer
from rapidfuzz import fuzz, process
from rich.console import Console

console = Console()


# --- Modelo ---------------------------------------------------------------


@dataclass
class RegistroEtiquetacao:
    """Uma linha do dataset a etiquetar, antes de virar registro no SQLite."""

    endereco: str
    extras: str
    meta: dict[str, Any]
    origem: str
    origem_id: str | None = None


# --- Filtro de diversidade ------------------------------------------------


class FiltroDiversidade(ABC):
    """Decide se um endereço sorteado entra no dataset (para aumentar a diversidade)."""

    @abstractmethod
    def aceitar(self, endereco: str) -> bool:
        """True se `endereco` pode entrar no dataset (não fere a diversidade)."""


class SemFiltroDiversidade(FiltroDiversidade):
    """Aceita tudo — usado quando nenhum limiar de diversidade é informado."""

    def aceitar(self, endereco: str) -> bool:
        return True


class FiltroDiversidadeFuzzy(FiltroDiversidade):
    """Descarta sorteados parecidos demais com endereços já aceitos (rapidfuzz).

    Compara cada candidato com os endereços já presentes (baseline do banco +
    aceitos nesta rodada) e rejeita quando a similaridade alcança o limiar.
    `similaridade_maxima` e `distancia_minima` são complementares, na escala
    0–100 do rapidfuzz (`distancia = 100 - similaridade`).
    """

    def __init__(
        self,
        aceitos: Iterable[str] = (),
        *,
        similaridade_maxima: float | None = None,
    ) -> None:
        self.aceitos: list[str] = list(aceitos)
        self.limite = 0.0
        if similaridade_maxima is not None:
            self.limite = max(self.limite, similaridade_maxima)

    def aceitar(self, endereco: str) -> bool:
        # `score_cutoff` corta cedo: só interessa um match >= limite.
        if process.extractOne(
            endereco,
            self.aceitos,
            scorer=fuzz.token_sort_ratio,
            score_cutoff=self.limite,
        ):
            return False
        self.aceitos.append(endereco)
        return True


# --- Populadores ----------------------------------------------------------


def converter_float(valor: Any) -> float | None:
    """Converte números com vírgula decimal (ex.: '-8,0962257') em float."""
    if valor is None:
        return None
    try:
        return float(str(valor).replace(",", "."))
    except ValueError:
        return None


def montar_extras(
    municipio: str | None, uf: str | None, bairro: str | None, *, banco: str
) -> str:
    """Monta a 'extra info' (contexto; não popula segmentos)."""
    linhas: list[str] = []
    municipio_uf = "/".join(p for p in (municipio, uf) if p)
    if municipio_uf:
        linhas.append(f"Municipio: {municipio_uf}")
    if bairro:
        linhas.append(f"Bairro: {bairro}")
    if banco:
        linhas.append(f"Banco de Dados: {banco}")
    return "\n".join(linhas)


class Populador(ABC):
    """Lê uma origem e rende registros prontos para o dataset."""

    tipo: ClassVar[str]
    rotulo: ClassVar[str]

    def __init__(self, arquivo: Path, aba: str | None = None) -> None:
        self.arquivo = arquivo
        self.aba = aba

    @abstractmethod
    def popular(
        self,
        conn: duckdb.DuckDBPyConnection,
    ) -> Iterator[RegistroEtiquetacao]:
        """Percorre a origem em streaming, rendendo um registro por linha."""


class PopuladorImoveisUniao(Populador):
    """Imóveis da União (SPU): endereço já concatenado + geo.

    A consulta é um literal com placeholders (a extensão `excel` e o caminho
    entram como parâmetros, sem montar SQL com dados do usuário). A origem é
    percorrida em streaming, em lotes; a amostragem e o filtro acontecem
    depois, sobre o stream (ver `amostrar_reservatorio`).
    """

    tipo = "imoveis_uniao"
    rotulo = "Imóveis da União (SPU)"
    TAM_LOTE: ClassVar[int] = 20_000

    CONSULTA: ClassVar[str] = """
        SELECT "Rip Imóvel", "UF", "Município", "Bairro", "Endereço",
               "Latitude", "Longitude", "Nível de Precisão"
        FROM read_xlsx(?, sheet = ?)
        WHERE "Endereço" IS NOT NULL AND trim("Endereço") <> ''
    """

    def popular(
        self,
        conn: duckdb.DuckDBPyConnection,
    ) -> Iterator[RegistroEtiquetacao]:
        conn.execute("INSTALL excel; LOAD excel;")
        resultado = conn.execute(
            self.CONSULTA, [str(self.arquivo), self.aba or "Sheet1"]
        )

        while True:
            linhas = resultado.fetchmany(self.TAM_LOTE)
            if not linhas:
                break
            for linha in linhas:
                rip, uf, municipio, bairro, endereco, lat, lon, precisao = linha
                yield RegistroEtiquetacao(
                    endereco=str(endereco).strip(),
                    extras=montar_extras(
                        municipio, uf, bairro, banco="Imóveis da União"
                    ),
                    meta={
                        "latitude": converter_float(lat),
                        "longitude": converter_float(lon),
                        "nivel_precisao": precisao,
                        "arquivo": str(self.arquivo),
                        "aba": self.aba or "Sheet1",
                    },
                    origem=self.tipo,
                    origem_id=str(rip),
                )


POPULADORES: dict[str, type[Populador]] = {
    PopuladorImoveisUniao.tipo: PopuladorImoveisUniao,
}


def carregar_populador(tipo: str, arquivo: Path, aba: str | None) -> Populador:
    classe = POPULADORES.get(tipo)
    if classe is None:
        opcoes = ", ".join(sorted(POPULADORES))
        raise typer.BadParameter(
            f"tipo_dataset desconhecido: {tipo!r}. Opções: {opcoes}."
        )
    return classe(arquivo, aba)


# --- Destino SQLite -------------------------------------------------------


def calcular_hash(endereco: str) -> str:
    return hashlib.sha256(endereco.encode("utf-8")).hexdigest()


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
                (id, endereco, extras, meta, origem, origem_id, lote,
                 hash_endereco, data_criacao)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                base_ns + i,
                r.endereco,
                r.extras,
                json.dumps(r.meta, ensure_ascii=False),
                r.origem,
                r.origem_id,
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


# --- Amostragem -----------------------------------------------------------


@dataclass
class ResultadoAmostragem:
    amostra: list[RegistroEtiquetacao]
    candidatos: int
    aceitos: int


def reservatorio(
    fonte: Iterator[RegistroEtiquetacao],
    tamanho: int,
    seed: int | None,
) -> list[RegistroEtiquetacao]:
    """Reservoir sampling (Algoritmo R): amostra uniforme de `tamanho`.

    Um único passe e memória constante (`tamanho` registros), independente do
    tamanho da origem.
    """
    rnd = random.Random(seed)
    reserva: list[RegistroEtiquetacao] = []

    for i, registro in enumerate(fonte):
        if i < tamanho:
            reserva.append(registro)
        else:
            # Troca com probabilidade tamanho / (i + 1).
            escolhido = rnd.randrange(i + 1)
            if escolhido < tamanho:
                reserva[escolhido] = registro

    return reserva


def amostrar_diverso(
    populador: Populador,
    criar_filtro: Callable[[], FiltroDiversidade],
    *,
    tamanho: int,
    seed: int | None,
    fator_inicial: int = 3,
    max_rodadas: int = 2,
) -> ResultadoAmostragem:
    """Amostra `tamanho` endereços diversos, repetindo até atingir o pedido.

    Cada rodada faz um reservoir de `tamanho * fator` candidatos (uma leitura
    da origem) e aplica o filtro de diversidade sobre esse pool. Se não atingir
    o pedido, dobra o pool e tenta de novo. O pool é limitado de propósito: o
    filtro fuzzy custa O(pool) por candidato, então passar o filtro na origem
    inteira seria inviável.
    """
    fator = fator_inicial
    candidatos = 0
    aceitos = 0
    amostra: list[RegistroEtiquetacao] = []

    for _ in range(max_rodadas):
        conn = duckdb.connect()
        try:
            pool = reservatorio(populador.popular(conn), tamanho * fator, seed)
        finally:
            conn.close()

        filtro = criar_filtro()
        amostra = [r for r in tqdm.tqdm(pool) if filtro.aceitar(r.endereco)]
        candidatos, aceitos = len(pool), len(amostra)

        if aceitos >= tamanho:
            break
        fator *= 2

    return ResultadoAmostragem(amostra[:tamanho], candidatos, aceitos)


# --- CLI ------------------------------------------------------------------

app = typer.Typer(no_args_is_help=True, add_completion=False)


@app.command()
def popular(
    tipo_dataset: Annotated[
        str, typer.Argument(help="Chave do populador (ex.: imoveis_uniao).")
    ],
    arquivo: Annotated[Path, typer.Argument(help="Arquivo de origem.")],
    destino: Annotated[
        Path, typer.Argument(help="SQLite de destino (append se já existir).")
    ],
    tamanho_amostra: Annotated[
        int,
        typer.Option(
            "--tamanho-amostra", "-n", min=1, help="Qtd. de endereços sorteados."
        ),
    ] = 1000,
    seed: Annotated[
        int | None,
        typer.Option("--seed", help="Semente do sorteio (reprodutibilidade)."),
    ] = None,
    similaridade_maxima: Annotated[
        float | None,
        typer.Option(
            "--similaridade-maxima",
            help="Descarta sorteados com similaridade >= X (0–100, rapidfuzz).",
        ),
    ] = None,
    aba: Annotated[
        str | None, typer.Option("--aba", help="Aba da planilha (xlsx).")
    ] = None,
) -> None:
    """Sorteia endereços de uma origem e popula o dataset de etiquetagem."""
    if not arquivo.is_file():
        raise typer.BadParameter(f"Arquivo de origem não encontrado: {arquivo}")

    populador = carregar_populador(tipo_dataset, arquivo, aba)
    lote = montar_lote(tipo_dataset)

    destino.parent.mkdir(parents=True, exist_ok=True)
    conn_destino = sqlite3.connect(str(destino))
    try:
        criar_banco(conn_destino)

        existentes = (
            ler_enderecos_existentes(conn_destino)
            if similaridade_maxima is not None
            else []
        )

        def criar_filtro() -> FiltroDiversidade:
            if similaridade_maxima is None:
                return SemFiltroDiversidade()
            return FiltroDiversidadeFuzzy(
                existentes, similaridade_maxima=similaridade_maxima
            )

        if similaridade_maxima is not None:
            console.print(
                f"[dim]Filtro fuzzy comparando com {len(existentes)} "
                "endereços já no banco.[/dim]"
            )
        console.print(
            f"[bold]{populador.rotulo}[/bold] — lendo a origem e "
            f"amostrando até {tamanho_amostra} endereços…"
        )

        resultado = amostrar_diverso(
            populador,
            criar_filtro,
            tamanho=tamanho_amostra,
            seed=seed,
            # Sem filtro não há descarte: o pool já é o tamanho final.
            fator_inicial=1 if similaridade_maxima is None else 3,
        )

        inseridos, ignorados = gravar_registros(conn_destino, resultado.amostra, lote)
        total = contar_registros(conn_destino)
    finally:
        conn_destino.close()

    descartados = resultado.candidatos - resultado.aceitos
    console.rule("Resumo")
    console.print(f"Lote: [bold]{lote}[/bold]")
    console.print(f"Candidatos (pool): {resultado.candidatos}")
    if descartados:
        console.print(f"Descartados por diversidade: [yellow]{descartados}[/yellow]")
    console.print(
        f"Tamanho da amostra: [bold]{len(resultado.amostra)}[/bold] / {tamanho_amostra}"
    )
    console.print(f"Inseridos: [green]{inseridos}[/green]")
    console.print(f"Ignorados (hash duplicado): {ignorados}")
    console.print(f"Total no banco: [bold]{total}[/bold]")


if __name__ == "__main__":
    app()
