"""Comando que popula o dataset de anotacao."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Annotated

import typer

from crf_endereco.anotacao.populacao import carregar_fonte
from crf_endereco.anotacao.populacao.amostragem import amostrar_diverso
from crf_endereco.dataset import (
    contar_registros,
    criar_banco,
    gravar_registros,
    ler_enderecos_existentes,
    montar_lote,
)
from crf_endereco.ui import console


def popular(
    tipo_dataset: Annotated[
        str, typer.Argument(help="Chave da base (ex.: imoveis_uniao).")
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
    if not arquivo.exists():
        raise typer.BadParameter(f"Origem não encontrada: {arquivo}")

    fonte = carregar_fonte(tipo_dataset)
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
        if similaridade_maxima is not None:
            console.print(
                f"[dim]Filtro fuzzy comparando com {len(existentes)} "
                "endereços já no banco.[/dim]"
            )
        console.print(
            f"[bold]{fonte.rotulo}[/bold] — lendo a origem e "
            f"amostrando até {tamanho_amostra} endereços…"
        )

        resultado = amostrar_diverso(
            fonte,
            arquivo,
            tamanho=tamanho_amostra,
            seed=seed,
            similaridade_maxima=similaridade_maxima,
            existentes=existentes,
            aba=aba,
        )
        escrita = gravar_registros(conn_destino, resultado.amostra, lote)
        total = contar_registros(conn_destino)
    finally:
        conn_destino.close()

    descartados = resultado.candidatos - resultado.aceitos
    console.rule("Resumo")
    console.print(f"Lote: [bold]{lote}[/bold]")
    console.print(f"Candidatos avaliados: {resultado.candidatos}")
    if descartados:
        console.print(f"Descartados por diversidade: [yellow]{descartados}[/yellow]")
    console.print(
        f"Tamanho da amostra: [bold]{len(resultado.amostra)}[/bold] / {tamanho_amostra}"
    )
    console.print(f"Inseridos: [green]{escrita.inseridos}[/green]")
    console.print(f"Ignorados (hash duplicado): {escrita.ignorados}")
    console.print(f"Total no banco: [bold]{total}[/bold]")
