"""Comandos que produzem o dataset: popular e etiquetar."""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import asdict, replace
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.pretty import pprint

from crf_endereco.anotacao.agente import criar_agente, fechar_agente, segmentar
from crf_endereco.anotacao.filtro_crf import prever_tipos, validar_tipos
from crf_endereco.anotacao.lote import Opcoes, dividir_filtros, executar_lote
from crf_endereco.anotacao.pendentes import Filtros, pendentes
from crf_endereco.anotacao.populacao import carregar_fonte
from crf_endereco.anotacao.populacao.amostragem import amostrar_diverso
from crf_endereco.config import carregar_config
from crf_endereco.dataset import (
    abrir_banco,
    contar_registros,
    criar_banco,
    gravar_registros,
    ler_enderecos_existentes,
    montar_lote,
)
from crf_endereco.ui import console

app = typer.Typer(no_args_is_help=True, add_completion=False)

# Opcoes repetidas entre os comandos de anotacao.
OpcaoEnv = Annotated[Path, typer.Option("--env", help="Caminho do arquivo .env.")]
OpcaoIteracoes = Annotated[
    int,
    typer.Option("--iteracoes", "-n", min=1, help="Máximo de rodadas do loop reAct."),
]
OpcaoTolerancia = Annotated[
    int,
    typer.Option(
        "--tolerancia-erro",
        min=0,
        help="Falhas de validação consecutivas antes de abortar.",
    ),
]


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
    env: OpcaoEnv = Path(".env"),
    iteracoes: OpcaoIteracoes = 10,
    tolerancia_erro: OpcaoTolerancia = 2,
    saida: Annotated[
        Path | None,
        typer.Option("--saida", "-o", help="Arquivo JSON de saída (padrão: stdout)."),
    ] = None,
    com_cnefe: Annotated[
        bool,
        typer.Option(
            "--com-cnefe",
            help="Liga a ferramenta de SQL sobre o CNEFE (desligada por padrão).",
        ),
    ] = True,
) -> None:
    """Segmenta um endereço bruto em campos rotulados usando uma LLM."""
    agente = criar_agente(carregar_config(env, com_cnefe=com_cnefe), console)
    try:
        resultado = segmentar(
            agente, endereco, extras, n_iter=iteracoes, tolerancia_erro=tolerancia_erro
        )
    finally:
        fechar_agente(agente)

    console.rule("Resultado final")
    pprint(resultado)

    texto = json.dumps(
        {
            "endereco": endereco,
            "extras": extras,
            "segmentos": [asdict(segmento) for segmento in resultado.segmentos],
            "comentario": resultado.comentario,
        },
        ensure_ascii=False,
        indent=2,
    )
    if saida:
        _ = saida.write_text(texto, encoding="utf-8")
        console.print(f"[green]Salvo em {saida}[/green]")
    else:
        console.print(texto)


@app.command()
def lote(
    banco: Annotated[Path, typer.Argument(help="SQLite do dataset de etiquetagem.")],
    env: OpcaoEnv = Path(".env"),
    iteracoes: OpcaoIteracoes = 10,
    tolerancia_erro: OpcaoTolerancia = 2,
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
            "--uf", help="Filtra o lote por UF (repita ou separe por vírgula)."
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
            "--origem", help="Filtra o lote por origem (repita ou separe por vírgula)."
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
    apenas_erros: Annotated[
        bool,
        typer.Option(
            "--apenas-erros",
            help="Processa SOMENTE linhas com erro anterior (não os nunca-anotados).",
        ),
    ] = False,
    com_cnefe: Annotated[
        bool,
        typer.Option(
            "--com-cnefe",
            help="Liga a ferramenta de SQL sobre o CNEFE (desligada por padrão).",
        ),
    ] = True,
    balancear: Annotated[
        bool,
        typer.Option(
            "--balancear/--sem-balancear",
            help="Sorteia o lote alternando entre células (UF, origem) e priorizando "
            "as menos anotadas.",
        ),
    ] = True,
    apenas_tipos: Annotated[
        list[str] | None,
        typer.Option(
            "--apenas-tipos",
            help=(
                "Processa só endereços em que o CRF prevê ao menos um destes tipos "
                "(repita ou separe por vírgula). O modelo roda em todos os pendentes "
                "(não só em --limite) antes de etiquetar."
            ),
        ),
    ] = None,
    modelo_crf: Annotated[
        Path | None,
        typer.Option(
            "--modelo-crf",
            help=(
                "tagger.crf usado em --apenas-tipos (padrão: o modelo padrão do "
                "enderecobr_rs, ou ENDERECOBR_MODELO)."
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
        incluir_erros=retentar_erros or apenas_erros,
        apenas_erros=apenas_erros,
        ufs=dividir_filtros(uf),
        origens=dividir_filtros(origem),
        municipios=dividir_filtros(municipio),
    )
    # Valida os argumentos antes de tocar no ambiente (falha rápida, sem .env).
    tipos = validar_tipos(dividir_filtros(apenas_tipos), modelo_crf)
    if binario_crf is not None and not binario_crf.is_file():
        raise typer.BadParameter(
            f"Binário do segmentador não encontrado: {binario_crf}"
        )

    config = carregar_config(env, com_cnefe=com_cnefe)
    console_llm = console if verboso else Console(quiet=True)

    # Valida o ambiente (CNEFE, municipios) uma vez, antes de começar o lote.
    fechar_agente(criar_agente(config, console))

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

        linhas = pendentes(conn, filtros, limite if balancear else None)
        if not linhas:
            console.print("[yellow]Nenhum endereço pendente para processar.[/yellow]")
            return

        console.print(
            f"[bold]{len(linhas)}[/bold] endereço(s) a processar — modelo "
            f"[bold]{config.api_model}[/bold], concorrência {concorrencia}."
        )
        inicio = time.perf_counter()
        resumo = executar_lote(
            conn,
            config,
            linhas,
            Opcoes(iteracoes, tolerancia_erro, concorrencia),
            console_llm=console_llm,
        )
        duracao = time.perf_counter() - inicio
    finally:
        conn.close()

    console.rule("Resumo")
    console.print(f"Sucesso: [green]{resumo.sucesso}[/green]")
    if resumo.erro:
        console.print(
            f"Erros: [yellow]{resumo.erro}[/yellow] "
            "(use --retentar-erros para reprocessar)"
        )
    console.print(f"Total: [bold]{resumo.total}[/bold] em {duracao:.1f}s")


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
    lote_id = montar_lote(tipo_dataset)
    destino.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(destino))
    try:
        criar_banco(conn)
        existentes = (
            ler_enderecos_existentes(conn) if similaridade_maxima is not None else []
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
        escrita = gravar_registros(conn, resultado.amostra, lote_id)
        total = contar_registros(conn)
    finally:
        conn.close()

    descartados = resultado.candidatos - resultado.aceitos
    console.rule("Resumo")
    console.print(f"Lote: [bold]{lote_id}[/bold]")
    console.print(f"Candidatos avaliados: {resultado.candidatos}")
    if descartados:
        console.print(f"Descartados por diversidade: [yellow]{descartados}[/yellow]")
    console.print(
        f"Tamanho da amostra: [bold]{len(resultado.amostra)}[/bold] / {tamanho_amostra}"
    )
    console.print(f"Inseridos: [green]{escrita.inseridos}[/green]")
    console.print(f"Ignorados (hash duplicado): {escrita.ignorados}")
    console.print(f"Total no banco: [bold]{total}[/bold]")
