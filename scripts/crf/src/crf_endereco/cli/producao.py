"""Comandos que produzem o dataset: popular e etiquetar."""

from __future__ import annotations

import json
import sqlite3
import time
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from functools import partial
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.padding import Padding
from rich.pretty import pprint
from rich.table import Table
from rich.text import Text

from crf_endereco.anotacao.agente import Pedido, criar_agente, fechar_agente, segmentar
from crf_endereco.anotacao.filtro_crf import (
    Divergencia,
    Previsao,
    parse_faixa,
    validar_tipos,
)
from crf_endereco.anotacao.lote import (
    Gravacao,
    Opcoes,
    compor_lotes,
    dividir_filtros,
    executar_lote,
)
from crf_endereco.anotacao.pendentes import Pendente, pendentes
from crf_endereco.anotacao.populacao import carregar_fonte
from crf_endereco.anotacao.populacao.amostragem import amostrar_diverso
from crf_endereco.cli.filtros import (
    ESTILO_VEREDITO,
    OpcaoApenasTipos,
    OpcaoBalancear,
    OpcaoBusca,
    OpcaoIncertos,
    OpcaoIncertosMedia,
    OpcaoIncluirRevisados,
    OpcaoLimite,
    OpcaoLote,
    OpcaoModelo,
    OpcaoMunicipio,
    OpcaoOrigem,
    OpcaoUf,
    filtrar_por_previsao,
    montar_filtros,
    pares_abreviados,
    precisa_do_crf,
    prever_recorte,
    recortar_divergentes,
)
from crf_endereco.config import CAMINHO_TAGGER, carregar_config
from crf_endereco.dataset import (
    abrir_banco,
    contar_registros,
    criar_banco,
    gravar_registros,
    ler_enderecos_existentes,
    montar_lote,
)
from crf_endereco.features import tokenize
from crf_endereco.modelo.crf import nome_do_modelo
from crf_endereco.rotulos import Mudanca, comparar, mergear
from crf_endereco.ui import console, estilo_rotulo

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
            help="Liga a ferramenta de SQL sobre o CNEFE (ligada por padrão; "
            "use --no-com-cnefe para desligar).",
        ),
    ] = True,
) -> None:
    """Segmenta um endereço bruto em campos rotulados usando uma LLM."""
    agente = criar_agente(carregar_config(env, com_cnefe=com_cnefe), console)
    try:
        resultado = segmentar(
            agente,
            [Pedido(endereco, extras)],
            n_iter=iteracoes,
            tolerancia_erro=tolerancia_erro,
        )
    finally:
        fechar_agente(agente)

    resposta = resultado.aceitas.get(0)
    if resposta is None:
        raise typer.BadParameter(resultado.falhas.get(0, "sem resposta"))

    console.rule("Resultado final")
    pprint(resposta)

    texto = json.dumps(
        {
            "endereco": endereco,
            "extras": extras,
            "segmentos": [asdict(segmento) for segmento in resposta.segmentos],
            "comentario": resposta.comentario,
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
    limite: OpcaoLimite = None,
    lote_id: OpcaoLote = None,
    uf: OpcaoUf = None,
    municipio: OpcaoMunicipio = None,
    origem: OpcaoOrigem = None,
    concorrencia: Annotated[
        int,
        typer.Option("--concorrencia", "-c", min=1, help="Chamadas simultâneas à LLM."),
    ] = 1,
    tamanho_lote: Annotated[
        int,
        typer.Option(
            "--tamanho-lote",
            "-b",
            min=1,
            help="Endereços por conversa; 1 etiqueta um endereço por chamada.",
        ),
    ] = 5,
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
    divergentes: Annotated[
        bool,
        typer.Option(
            "--divergentes",
            help=(
                "Reetiqueta os endereços do recorte de treino do modelo em que ele "
                "erra o próprio rótulo: ali ele já viu o exemplo, então o erro "
                "aponta rótulo suspeito. O rótulo trocado fica em meta.revisoes."
            ),
        ),
    ] = False,
    incluir_revisados: OpcaoIncluirRevisados = False,
    com_cnefe: Annotated[
        bool,
        typer.Option(
            "--com-cnefe",
            help="Liga a ferramenta de SQL sobre o CNEFE (ligada por padrão; "
            "use --no-com-cnefe para desligar).",
        ),
    ] = True,
    balancear: OpcaoBalancear = True,
    apenas_tipos: OpcaoApenasTipos = None,
    incertos: OpcaoIncertos = None,
    incertos_media: OpcaoIncertosMedia = None,
    busca: OpcaoBusca = None,
    modelo: OpcaoModelo = CAMINHO_TAGGER,
    verboso: Annotated[
        bool,
        typer.Option(
            "--verboso", help="Mostra raciocínio e tool-calls de cada endereço."
        ),
    ] = False,
) -> None:
    """Processa em lote os endereços pendentes do dataset de etiquetagem."""
    filtros = montar_filtros(
        lote=lote_id,
        uf=uf,
        municipio=municipio,
        origem=origem,
        busca=busca,
        balancear=balancear,
        incluir_erros=retentar_erros or apenas_erros,
        apenas_erros=apenas_erros,
    )
    # Valida os argumentos antes de tocar no ambiente (falha rápida, sem .env).
    tipos = validar_tipos(dividir_filtros(apenas_tipos))
    faixa_incertos = parse_faixa(incertos, "--incertos")
    faixa_media = parse_faixa(incertos_media, "--incertos-media")
    if (
        precisa_do_crf(tipos, faixa_incertos, faixa_media, divergentes=divergentes)
        and not modelo.is_file()
    ):
        raise typer.BadParameter(f"Modelo CRF não encontrado: {modelo}")

    config = carregar_config(env, com_cnefe=com_cnefe)
    console_llm = console if verboso else Console(quiet=True)

    # Valida o ambiente (CNEFE, municipios) uma vez, antes de começar o lote.
    fechar_agente(criar_agente(config, console))

    previsoes: list[Previsao] = []
    divergencias_por_hash: dict[str, Divergencia] = {}
    conn = abrir_banco(banco)
    try:
        if divergentes:
            # Antes dos filtros de confiança: assim eles recortam os divergentes.
            filtros, divergencias_por_hash = recortar_divergentes(
                conn, filtros, banco, modelo, incluir_revisados=incluir_revisados
            )
        if precisa_do_crf(tipos, faixa_incertos, faixa_media):
            previsoes = prever_recorte(pendentes(conn, filtros), modelo)
            filtros = filtrar_por_previsao(
                filtros,
                previsoes,
                tipos=tipos,
                faixa_incertos=faixa_incertos,
                faixa_media=faixa_media,
            )

        grupos = compor_lotes(pendentes(conn, filtros), tamanho_lote, limite)
        linhas = [linha for grupo in grupos for linha in grupo]
        if not linhas:
            console.print("[yellow]Nenhum endereço pendente para processar.[/yellow]")
            return

        console.print(
            f"[bold]{len(linhas)}[/bold] endereço(s) em "
            f"[bold]{len(grupos)}[/bold] lote(s) de até {tamanho_lote} — modelo "
            f"[bold]{config.api_model}[/bold], concorrência {concorrencia}."
        )
        if previsoes or divergencias_por_hash:
            # Cada lote anuncia a própria dificuldade quando sai da fila: no
            # início, a lista inteira ocupava a tela antes de qualquer chamada.
            anunciar = partial(
                _anunciar_lote,
                confiancas={previsao.id: previsao for previsao in previsoes},
                divergentes=divergencias_por_hash,
            )
        else:
            anunciar = None
        # Depois da gravação de cada lote: o que a reetiquetação mudou.
        mostrar = (
            partial(_mostrar_mudancas, divergentes=divergencias_por_hash)
            if divergencias_por_hash
            else None
        )

        inicio = time.perf_counter()
        resumo = executar_lote(
            conn,
            config,
            grupos,
            Opcoes(iteracoes, tolerancia_erro, concorrencia),
            console_llm=console_llm,
            revisado_por=nome_do_modelo(modelo) if divergentes else None,
            ao_iniciar_lote=anunciar,
            ao_gravar_lote=mostrar,
        )
        duracao = time.perf_counter() - inicio
    finally:
        conn.close()

    console.rule("Resumo")
    console.print(f"Sucesso: [green]{resumo.sucesso}[/green]")
    if resumo.erro:
        dica = (
            "(a linha que falha numa revisão não é gravada: rode de novo)"
            if divergentes
            else "(use --retentar-erros para reprocessar)"
        )
        console.print(f"Erros: [yellow]{resumo.erro}[/yellow] {dica}")
    if resumo.interrompido:
        restantes = resumo.total - resumo.sucesso - resumo.erro
        console.print(
            f"Interrompido: [yellow]{restantes}[/yellow] endereço(s) não processados."
        )
    console.print(f"Total: [bold]{resumo.total}[/bold] em {duracao:.1f}s")


def _anunciar_lote(
    numero: int,
    total: int,
    grupo: Sequence[Pendente],
    *,
    confiancas: Mapping[int, Previsao],
    divergentes: Mapping[str, Divergencia],
) -> None:
    """Dificuldade do lote na hora em que ele começa.

    Endereço a endereço: média geométrica das probabilidades dos tokens e a do
    token menos confiável (do CRF), mais o que o modelo troca onde diverge.
    """
    visiveis = [confiancas[linha.id] for linha in grupo if linha.id in confiancas]
    cabeca = f"[dim]lote {numero}/{total}[/dim]"
    if visiveis:
        media = sum(previsao.media_confianca for previsao in visiveis) / len(visiveis)
        minima = min(previsao.menor_confianca for previsao in visiveis)
        cabeca += f" · média {media:.2f} · mínima {minima:.2f}"
    no_lote = sum(1 for linha in grupo if linha.hash in divergentes)
    if no_lote:
        cabeca += f" · [yellow]{no_lote} divergente(s)[/yellow]"
    console.print(cabeca)

    for linha in grupo:
        previsao = confiancas.get(linha.id)
        confianca = (
            f"[dim]{previsao.media_confianca:.2f}/{previsao.menor_confianca:.2f}[/dim]  "
            if previsao is not None
            else ""
        )
        achado = divergentes.get(linha.hash)
        resto = f"  [yellow]{pares_abreviados(achado.pares)}[/yellow]" if achado else ""
        console.print(f"  {confianca}{linha.endereco}{resto}")


def _mostrar_mudancas(
    numero: int,
    total: int,
    grupo: Sequence[Pendente],
    gravacoes: Sequence[Gravacao],
    *,
    divergentes: Mapping[str, Divergencia],
) -> None:
    """O que a reetiquetação fez em cada divergente do lote.

    As três etiquetas lado a lado — a do treino, a que o CRF previu e a que a
    LLM acabou de dar — restritas aos tokens em que elas não batem.
    """
    respostas = {
        id_linha: resposta for id_linha, resposta, sucesso in gravacoes if sucesso
    }
    blocos: list[tuple[str, str, list[Mudanca]]] = []
    for linha in grupo:
        achado = divergentes.get(linha.hash)
        resposta = respostas.get(linha.id)
        if achado is None or resposta is None:
            continue
        try:
            segmentos = json.loads(resposta).get("segmentos", [])
        except json.JSONDecodeError:
            # O banco e escrito por `json.dumps`, mas uma linha editada a mao nao
            # pode derrubar um lote inteiro so porque a tabela nao aparece.
            console.print(f"[yellow]resposta inválida em {linha.endereco!r}[/yellow]")
            continue
        tokens, agora = mergear(linha.endereco, segmentos, tokenize)
        mudancas, veredito = comparar(tokens, achado.rotulos, achado.previsto, agora)
        if mudancas:
            blocos.append((linha.endereco, veredito, mudancas))
    if not blocos:
        return

    console.print(f"[dim]lote {numero}/{total} · o que a reetiquetação mudou[/dim]")
    for endereco, veredito, mudancas in blocos:
        console.print(
            f"  [bold]{endereco}[/bold] [{ESTILO_VEREDITO[veredito]}]{veredito}[/]"
        )
        tabela = Table(
            box=None, pad_edge=False, padding=(0, 1, 0, 0), header_style="dim"
        )
        tabela.add_column("token", style="bold")
        tabela.add_column("original")
        tabela.add_column("crf")
        tabela.add_column("agora")
        for mudanca in mudancas:
            tabela.add_row(
                mudanca.token,
                Text(mudanca.antes, style="yellow"),
                Text(mudanca.previsto, style=estilo_rotulo(mudanca.previsto)),
                Text(mudanca.agora, style=estilo_rotulo(mudanca.agora)),
            )
        console.print(Padding(tabela, (0, 0, 0, 2), expand=False))


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
