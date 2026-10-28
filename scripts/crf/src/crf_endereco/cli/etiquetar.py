"""Comandos de anotacao por LLM."""

from __future__ import annotations

import json
import time
from dataclasses import asdict, replace
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.pretty import pprint

from crf_endereco.anotacao.filtro_crf import prever_tipos, validar_tipos
from crf_endereco.anotacao.lote import OpcoesLote, _dividir_filtros, executar_lote
from crf_endereco.anotacao.pendentes import Filtros, pendentes
from crf_endereco.anotacao.segmentacao import Contexto, segmentar
from crf_endereco.config import carregar_config
from crf_endereco.dataset import abrir_banco
from crf_endereco.ui import console

app = typer.Typer(no_args_is_help=True, add_completion=False)


@app.command()
def avulso(
    endereco: Annotated[str, typer.Argument(help="Endereço bruto a segmentar.")],
    extras: Annotated[
        str,
        typer.Option(
            "--extras",
            "-e",
            help="Informação extra de contexto (NÃO popula segmentos).",
        ),
    ] = "",
    env: Annotated[
        Path,
        typer.Option("--env", help="Caminho do arquivo .env."),
    ] = Path(".env"),
    iteracoes: Annotated[
        int,
        typer.Option(
            "--iteracoes", "-n", min=1, help="Máximo de rodadas do loop reAct."
        ),
    ] = 10,
    tolerancia_erro: Annotated[
        int,
        typer.Option(
            "--tolerancia-erro",
            min=0,
            help="Falhas de validação consecutivas antes de abortar.",
        ),
    ] = 2,
    saida: Annotated[
        Path | None,
        typer.Option("--saida", "-o", help="Arquivo JSON de saída (padrão: stdout)."),
    ] = None,
) -> None:
    """Segmenta um endereço bruto em campos rotulados usando uma LLM."""
    contexto = Contexto.criar(carregar_config(env), console)
    try:
        resultado = segmentar(
            contexto,
            endereco,
            extras,
            n_iter=iteracoes,
            tolerancia_erro=tolerancia_erro,
        )
    finally:
        contexto.fechar()

    console.rule("Resultado final")
    pprint(resultado)

    dados = {
        "endereco": endereco,
        "extras": extras,
        "segmentos": [asdict(seg) for seg in resultado.segmentos],
        "comentario": resultado.comentario,
    }
    texto = json.dumps(dados, ensure_ascii=False, indent=2)

    if saida:
        saida.write_text(texto, encoding="utf-8")
        console.print(f"[green]Salvo em {saida}[/green]")
    else:
        console.print(texto)


@app.command()
def lote(
    banco: Annotated[
        Path, typer.Argument(help="SQLite gerado por dataset_etiquetacao.py.")
    ],
    env: Annotated[
        Path,
        typer.Option("--env", help="Caminho do arquivo .env."),
    ] = Path(".env"),
    iteracoes: Annotated[
        int,
        typer.Option(
            "--iteracoes", "-n", min=1, help="Máximo de rodadas do loop reAct."
        ),
    ] = 10,
    tolerancia_erro: Annotated[
        int,
        typer.Option(
            "--tolerancia-erro",
            min=0,
            help="Falhas de validação consecutivas antes de abortar.",
        ),
    ] = 2,
    limite: Annotated[
        int | None,
        typer.Option("--limite", "-l", min=1, help="Processa no máximo N pendentes."),
    ] = None,
    lote_id: Annotated[
        str | None,
        typer.Option("--lote", help="Filtra as linhas por lote (coluna `lote`)."),
    ] = None,
    uf: Annotated[
        list[str] | None,
        typer.Option(
            "--uf",
            help="Filtra o lote por UF (repita ou separe por vírgula).",
        ),
    ] = None,
    municipio: Annotated[
        list[str] | None,
        typer.Option(
            "--municipio",
            help="Filtra o lote por município (repita ou separe por vírgula).",
        ),
    ] = None,
    origem: Annotated[
        list[str] | None,
        typer.Option(
            "--origem",
            help="Filtra o lote por origem (repita ou separe por vírgula).",
        ),
    ] = None,
    concorrencia: Annotated[
        int,
        typer.Option("--concorrencia", "-c", min=1, help="Chamadas simultâneas à LLM."),
    ] = 1,
    retentar_erros: Annotated[
        bool,
        typer.Option(
            "--retentar-erros",
            help="Reprocessa linhas cujo resultado anterior foi um erro.",
        ),
    ] = False,
    balancear: Annotated[
        bool,
        typer.Option(
            "--balancear/--sem-balancear",
            help="Sorteia o lote com cotas hierárquicas UF→origem (1/(anotados+1)).",
        ),
    ] = True,
    apenas_tipos: Annotated[
        list[str] | None,
        typer.Option(
            "--apenas-tipos",
            help=(
                "Processa só endereços em que o CRF prevê ao menos um destes "
                "tipos (repita ou separe por vírgula). O modelo roda em todos "
                "os pendentes (não só em --limite) antes de etiquetar."
            ),
        ),
    ] = None,
    modelo_crf: Annotated[
        Path | None,
        typer.Option(
            "--modelo-crf",
            help=(
                "tagger.crf usado em --apenas-tipos (padrão: o modelo padrão "
                "do enderecobr_rs, ou ENDERECOBR_MODELO)."
            ),
        ),
    ] = None,
    binario_crf: Annotated[
        Path | None,
        typer.Option(
            "--binario-crf",
            help=(
                "Binário `padronizar` do enderecobr_rs (padrão: "
                "target/{release,debug}/padronizar ou `cargo run`)."
            ),
        ),
    ] = None,
    verboso: Annotated[
        bool,
        typer.Option(
            "--verboso", help="Mostra raciocínio e tool-calls de cada endereço."
        ),
    ] = False,
) -> None:
    """Processa em lote os endereços pendentes do dataset de etiquetagem."""
    filtros = Filtros(
        lote=lote_id,
        incluir_erros=retentar_erros,
        ufs=_dividir_filtros(uf) or (),
        origens=_dividir_filtros(origem) or (),
        municipios=_dividir_filtros(municipio) or (),
    )
    # Valida os argumentos antes de tocar no ambiente (falha rapida, sem .env).
    tipos = validar_tipos(_dividir_filtros(apenas_tipos), modelo_crf)
    if binario_crf is not None and not binario_crf.is_file():
        raise typer.BadParameter(
            f"Binário do segmentador não encontrado: {binario_crf}"
        )

    config = carregar_config(env)
    console_llm = console if verboso else Console(quiet=True)

    # Valida o ambiente (CNEFE, municipios) uma vez, antes de comecar o lote.
    Contexto.criar(config, console).fechar()

    conn = abrir_banco(banco)
    try:
        if tipos:
            candidatos = pendentes(conn, filtros)
            console.print(
                f"[dim]Segmentando {len(candidatos)} pendente(s) para filtrar "
                f"por {', '.join(sorted(tipos))}...[/dim]"
            )
            aprovados = prever_tipos(
                candidatos, tipos, modelo=modelo_crf, binario=binario_crf
            )
            filtros = replace(filtros, ids=aprovados)
            console.print(
                f"[dim]Filtro do CRF: {len(aprovados)} de {len(candidatos)} "
                "endereço(s) com ao menos um tipo previsto.[/dim]"
            )

        quantidade = limite if balancear else None
        linhas = pendentes(conn, filtros, quantidade)
        if not linhas:
            console.print("[yellow]Nenhum endereço pendente para processar.[/yellow]")
            return

        console.print(
            f"[bold]{len(linhas)}[/bold] endereço(s) a processar — modelo [bold]{config.api_model}[/bold], concorrência {concorrencia}."
        )
        inicio = time.perf_counter()
        resumo = executar_lote(
            conn,
            config,
            linhas,
            OpcoesLote(iteracoes, tolerancia_erro, concorrencia),
            console_llm=console_llm,
        )
        duracao = time.perf_counter() - inicio
    finally:
        conn.close()

    console.rule("Resumo")
    console.print(f"Sucesso: [green]{resumo.sucesso}[/green]")
    if resumo.erro:
        console.print(
            f"Erros: [yellow]{resumo.erro}[/yellow] (use --retentar-erros para reprocessar)"
        )
    console.print(f"Total: [bold]{resumo.total}[/bold] em {duracao:.1f}s")
