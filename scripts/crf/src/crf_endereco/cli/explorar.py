"""Leitura do dataset: localiza e disseca os casos difíceis do CRF.

Nada aqui escreve no banco. O comando responde "onde o modelo sofre?" com as
mesmas lentes da etiquetagem (as flags de `cli.filtros`) e mostra, caso a caso,
as três camadas que explicam o endereço: o alvo atual (o que a LLM respondeu), a
previsão do CRF com a probabilidade de cada token, e o histórico de
reetiquetação. É a ferramenta para transformar "10% divergem" em "estes casos,
por isto".
"""

from __future__ import annotations

import sqlite3
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Annotated

import sklearn_crfsuite
import typer
from rich import box
from rich.table import Table
from rich.text import Text

from crf_endereco.anotacao.filtro_crf import (
    Divergencia,
    Previsao,
    parse_faixa,
    validar_tipos,
)
from crf_endereco.anotacao.lote import dividir_filtros
from crf_endereco.anotacao.pendentes import Pendente, pendentes
from crf_endereco.cli.filtros import (
    ESTILO_VEREDITO,
    OpcaoApenasTipos,
    OpcaoBusca,
    OpcaoIncertos,
    OpcaoIncertosMedia,
    OpcaoIncluirRevisados,
    OpcaoLote,
    OpcaoModelo,
    OpcaoMunicipio,
    OpcaoOrigem,
    OpcaoUf,
    filtrar_por_previsao,
    montar_filtros,
    pares_abreviados,
    prever_recorte,
    recortar_divergentes,
    recortar_recorte,
)
from crf_endereco.config import CAMINHO_TAGGER
from crf_endereco.dataset import Detalhe, abrir_banco, carregar_detalhes
from crf_endereco.features import ExtratorFeature, tokenize
from crf_endereco.modelo.crf import carregar_tagger
from crf_endereco.rotulos import (
    CONCORDA_COM_O_CRF,
    ROTULO_MANTIDO,
    ROTULO_NOVO,
    Mudanca,
    comparar,
    mergear,
)
from crf_endereco.ui import console, estilo_rotulo, estilo_tipo

# Papel do endereço no recorte gravado pelo treino, por valor de `--recorte`.
PAPEIS = {"todos": None, "treino": "treino", "teste": "teste"}

# Ordem em que os vereditos aparecem na lista: primeiro o que ainda é erro do
# modelo (`rótulo mantido`), por último o caso já resolvido.
ORDEM_VEREDITO = {ROTULO_MANTIDO: 0, ROTULO_NOVO: 1, CONCORDA_COM_O_CRF: 2}


def explorar(
    banco: Annotated[Path, typer.Argument(help="SQLite do dataset de etiquetagem.")],
    lote_id: OpcaoLote = None,
    uf: OpcaoUf = None,
    municipio: OpcaoMunicipio = None,
    origem: OpcaoOrigem = None,
    busca: OpcaoBusca = None,
    apenas_tipos: OpcaoApenasTipos = None,
    incertos: OpcaoIncertos = None,
    incertos_media: OpcaoIncertosMedia = None,
    modelo: OpcaoModelo = CAMINHO_TAGGER,
    divergentes: Annotated[
        bool,
        typer.Option(
            "--divergentes",
            help=(
                "Só o recorte de treino em que o modelo erra o próprio rótulo: ali "
                "ele já viu o exemplo, então o erro aponta rótulo suspeito."
            ),
        ),
    ] = False,
    incluir_revisados: OpcaoIncluirRevisados = False,
    revisados: Annotated[
        bool,
        typer.Option(
            "--revisados",
            help=(
                "Só linhas com histórico de reetiquetação (meta.revisoes), com o "
                "veredito de cada uma: o que a resposta nova fez com o rótulo."
            ),
        ),
    ] = False,
    sem_alvo: Annotated[
        bool,
        typer.Option(
            "--pendentes",
            help=(
                "Olha as linhas ainda sem alvo (nunca etiquetadas) em vez das já "
                "anotadas: é onde o CRF decide sozinho."
            ),
        ),
    ] = False,
    recorte: Annotated[
        str,
        typer.Option(
            "--recorte",
            help=(
                "Papel do endereço no recorte gravado do modelo: `treino` (ele "
                "viu), `teste` (nunca viu) ou `todos` (padrão)."
            ),
        ),
    ] = "todos",
    limite: Annotated[
        int, typer.Option("--limite", "-l", min=1, help="Quantos casos listar.")
    ] = 20,
    detalhar: Annotated[
        bool,
        typer.Option(
            "--detalhar",
            help="Disseca todos os casos da lista, token a token.",
        ),
    ] = False,
) -> None:
    """Explora o dataset: lista os casos difíceis e disseca os escolhidos."""
    if not modelo.is_file():
        raise typer.BadParameter(f"Modelo CRF não encontrado: {modelo}")
    if sem_alvo and (revisados or divergentes):
        raise typer.BadParameter(
            "--pendentes é exclusivo de --revisados e --divergentes: os dois só "
            "existem em linha já etiquetada."
        )

    tipos = validar_tipos(dividir_filtros(apenas_tipos))
    faixa_incertos = parse_faixa(incertos, "--incertos")
    faixa_media = parse_faixa(incertos_media, "--incertos-media")
    papel = _papel_do_recorte(recorte)

    filtros = montar_filtros(
        lote=lote_id,
        uf=uf,
        municipio=municipio,
        origem=origem,
        busca=busca,
        anotados=not sem_alvo,
        revisados=revisados,
    )
    conn = abrir_banco(banco)
    try:
        achados: dict[str, Divergencia] = {}
        if divergentes:
            filtros, achados = recortar_divergentes(
                conn, filtros, banco, modelo, incluir_revisados=incluir_revisados
            )
        filtros = recortar_recorte(conn, filtros, modelo, papel)

        candidatas = pendentes(conn, filtros)
        if not candidatas:
            console.print("[yellow]Nenhuma linha no recorte.[/yellow]")
            return
        previsoes = prever_recorte(candidatas, modelo)
        filtros = filtrar_por_previsao(
            filtros,
            previsoes,
            tipos=tipos,
            faixa_incertos=faixa_incertos,
            faixa_media=faixa_media,
        )
        por_id = {previsao.id: previsao for previsao in previsoes}
        linhas = [
            linha
            for linha in candidatas
            if filtros.ids is None or linha.id in filtros.ids
        ]
        if not linhas:
            console.print("[yellow]Nenhuma linha sobrou dos filtros.[/yellow]")
            return

        vereditos = _vereditos(conn, linhas, por_id) if revisados else {}
        listadas = _ordenar(linhas, por_id, achados, vereditos)[:limite]
        _listar(listadas, por_id, achados, vereditos)
        if detalhar:
            _dissecar(conn, listadas, por_id, achados, vereditos, modelo)
    finally:
        conn.close()


def _papel_do_recorte(valor: str) -> str | None:
    """`--recorte`: `todos` (ou o papel) do recorte gravado pelo `treinar`."""
    if valor not in PAPEIS:
        raise typer.BadParameter(
            f"--recorte: use {' ou '.join(PAPEIS)}, veio {valor!r}."
        )
    return PAPEIS[valor]


def _vereditos(
    conn: sqlite3.Connection, linhas: Sequence[Pendente], por_id: Mapping[int, Previsao]
) -> dict[int, str]:
    """Veredito de cada linha revisada: o que a reetiquetação fez com o rótulo."""
    detalhes = carregar_detalhes(conn, [linha.id for linha in linhas])
    vereditos: dict[int, str] = {}
    for linha in linhas:
        detalhe = detalhes.get(linha.id)
        if detalhe is None or not detalhe.revisoes or not detalhe.segmentos:
            continue
        vereditos[linha.id] = _comparar(detalhe, por_id[linha.id])[1]
    return vereditos


def _comparar(detalhe: Detalhe, previsao: Previsao) -> tuple[list[Mudanca], str]:
    """As três camadas do endereço: a etiqueta anterior, a do CRF e a atual.

    A anterior vem da última revisão — é o rótulo que treinou o modelo. Sem
    revisão as duas coincidem, e aí o veredito só olha o alvo atual contra o CRF.
    """
    tokens = tokenize(detalhe.endereco)
    _, agora = mergear(detalhe.endereco, list(detalhe.segmentos), tokenize)
    anteriores = _segmentos_anteriores(detalhe)
    if not anteriores:
        return comparar(tokens, agora, list(previsao.tags), agora)
    _, antes = mergear(detalhe.endereco, anteriores, tokenize)
    return comparar(tokens, antes, list(previsao.tags), agora)


def _segmentos_anteriores(detalhe: Detalhe) -> list[dict[str, str]]:
    """Segmentos que a última reetiquetação substituiu (vazio sem revisão)."""
    if not detalhe.revisoes:
        return []
    resposta = detalhe.revisoes[-1].get("resposta") or {}
    return list(resposta.get("segmentos") or [])


def _ordenar(
    linhas: Sequence[Pendente],
    por_id: Mapping[int, Previsao],
    achados: Mapping[str, Divergencia],
    vereditos: Mapping[int, str],
) -> list[Pendente]:
    """Do caso mais problemático para o menos.

    Divergente: primeiro quem o modelo troca em mais tokens, empate pela
    confiança. Revisado: primeiro o veredito que ainda é erro do modelo. Sem
    critério: só a confiança do CRF, do mais perdido ao mais seguro.
    """
    if achados:
        return sorted(
            linhas,
            key=lambda linha: (
                -len(achados[linha.hash].pares) if linha.hash in achados else 0,
                por_id[linha.id].media_confianca,
            ),
        )
    if vereditos:
        return sorted(
            linhas,
            key=lambda linha: (
                ORDEM_VEREDITO.get(vereditos.get(linha.id, ""), len(ORDEM_VEREDITO)),
                por_id[linha.id].media_confianca,
            ),
        )
    return sorted(linhas, key=lambda linha: por_id[linha.id].media_confianca)


def _listar(
    listadas: Sequence[Pendente],
    por_id: Mapping[int, Previsao],
    achados: Mapping[str, Divergencia],
    vereditos: Mapping[int, str],
) -> None:
    """Uma linha por caso: confiança, endereço e o sinal que o pôs na lista."""
    console.print(
        f"[bold]{len(listadas)}[/bold] caso(s) · {_resumo(achados, vereditos)}"
    )
    tabela = Table(
        box=box.SIMPLE_HEAD, pad_edge=False, show_edge=False, header_style="dim"
    )
    tabela.add_column("#", justify="right", style="dim")
    tabela.add_column("conf", justify="right")
    tabela.add_column("endereço", overflow="fold")
    tabela.add_column("sinal")
    for posicao, linha in enumerate(listadas, start=1):
        previsao = por_id[linha.id]
        achado = achados.get(linha.hash)
        veredito = vereditos.get(linha.id)
        if achado is not None:
            sinal = Text(pares_abreviados(achado.pares), style="yellow")
        elif veredito is not None:
            sinal = Text(veredito, style=ESTILO_VEREDITO[veredito])
        else:
            sinal = Text(
                f"{previsao.pior_token}→{previsao.pior_tag}",
                style=estilo_rotulo(previsao.pior_tag),
            )
        tabela.add_row(
            str(posicao),
            Text(
                f"{previsao.media_confianca:.2f}/{previsao.menor_confianca:.2f}",
                style=_estilo_confianca(previsao.media_confianca),
            ),
            linha.endereco,
            sinal,
        )
    console.print(tabela)


def _resumo(achados: Mapping[str, Divergencia], vereditos: Mapping[int, str]) -> str:
    """Como a lista está ordenada — e, entre revisados, o placar dos vereditos."""
    if achados:
        return "[dim]ordenados por tokens trocados, do mais errado ao menos[/dim]"
    if not vereditos:
        return (
            "[dim]ordenados pela confiança do CRF, do mais perdido ao mais seguro[/dim]"
        )
    contagem = Counter(vereditos.values())
    placar = " · ".join(
        f"{contagem[veredito]} {veredito}"
        for veredito in sorted(contagem, key=lambda v: ORDEM_VEREDITO.get(v, 9))
    )
    return f"[dim]revisados:[/dim] {placar}"


def _revisoes(quantidade: int) -> str:
    """`1 revisão` / `3 revisões`."""
    return f"{quantidade} revisão" if quantidade == 1 else f"{quantidade} revisões"


def _estilo_confianca(media: float) -> str:
    """Cor da confiança média: vermelho no caso perdido, verde no caso fácil."""
    if media < 0.5:
        return "red"
    if media < 0.75:
        return "yellow"
    return "green"


def _dissecar(
    conn: sqlite3.Connection,
    listadas: Sequence[Pendente],
    por_id: Mapping[int, Previsao],
    achados: Mapping[str, Divergencia],
    vereditos: Mapping[int, str],
    modelo: Path,
) -> None:
    """Disseca a lista inteira: tokens, marginais e o alvo da LLM, caso a caso."""
    detalhes = carregar_detalhes(conn, [linha.id for linha in listadas])
    crf = carregar_tagger(modelo)
    extrator = ExtratorFeature()
    for posicao, linha in enumerate(listadas, start=1):
        _caso(
            posicao,
            por_id[linha.id],
            detalhes[linha.id],
            crf,
            extrator,
            achados.get(linha.hash),
            vereditos.get(linha.id),
        )


def _caso(
    posicao: int,
    previsao: Previsao,
    detalhe: Detalhe,
    crf: sklearn_crfsuite.CRF,
    extrator: ExtratorFeature,
    achado: Divergencia | None,
    veredito: str | None,
) -> None:
    """Um caso dissecado: contexto, tabela token a token e o alvo atual."""
    console.print()
    console.rule(f"[bold]#{posicao}[/bold] {detalhe.endereco}")
    _contexto(detalhe, previsao, achado, veredito)
    _tokens(detalhe, previsao, crf, extrator)
    _alvo(detalhe)


def _contexto(
    detalhe: Detalhe,
    previsao: Previsao,
    achado: Divergencia | None,
    veredito: str | None,
) -> None:
    """De onde vem a linha e o que o CRF achou dela no conjunto."""
    console.print(
        f"[dim]origem={detalhe.origem} · uf={detalhe.uf} · "
        f"município={detalhe.municipio} · lote={detalhe.lote} · "
        f"recorte={detalhe.recorte or 'nenhum'} · llm={detalhe.llm or '—'}[/dim]"
    )
    for linha_extra in detalhe.extras.splitlines():
        console.print(f"[dim]  {linha_extra}[/dim]")
    console.print(
        f"confiança média {previsao.media_confianca:.2f} · mínima "
        f"{previsao.menor_confianca:.2f} · pior token "
        f"[bold]{previsao.pior_token!r}[/bold] "
        f"({previsao.pior_tag})"
    )
    if achado is not None:
        console.print(
            f"[yellow]divergente do rótulo do treino em "
            f"{len(achado.pares)} token(s)[/yellow]"
        )
    if detalhe.revisado_por is not None:
        veredito_txt = veredito or "sem veredito"
        console.print(
            f"revisado por [bold]{detalhe.revisado_por}[/bold] "
            f"({_revisoes(len(detalhe.revisoes))}) · "
            f"[{ESTILO_VEREDITO.get(veredito_txt, 'dim')}]{veredito_txt}[/]"
        )


def _tokens(
    detalhe: Detalhe,
    previsao: Previsao,
    crf: sklearn_crfsuite.CRF,
    extrator: ExtratorFeature,
) -> None:
    """Token a token: a etiqueta atual, a do CRF, a probabilidade e a rival.

    A coluna `antes` só existe em linha revisada: é o rótulo que treinou o
    modelo, o que a reetiquetação substituiu.
    """
    tokens = tokenize(detalhe.endereco)
    x = extrator.tokens2features(tokens)
    marginais = crf.predict_marginals_single(x) if x else []
    atual = (
        mergear(detalhe.endereco, list(detalhe.segmentos), tokenize)[1]
        if detalhe.segmentos
        else []
    )
    antes = (
        mergear(detalhe.endereco, _segmentos_anteriores(detalhe), tokenize)[1]
        if detalhe.revisoes
        else []
    )

    tabela = Table(box=None, pad_edge=False, padding=(0, 1, 0, 0), header_style="dim")
    tabela.add_column("token", style="bold")
    if antes:
        tabela.add_column("antes")
    tabela.add_column("atual")
    tabela.add_column("crf")
    tabela.add_column("p", justify="right", no_wrap=True)
    tabela.add_column("2ª", justify="right", no_wrap=True)
    for i, token in enumerate(tokens):
        previsto = previsao.tags[i] if i < len(previsao.tags) else ""
        marginal = marginais[i] if i < len(marginais) else {}
        rival, p_rival = _rival(marginal, previsto)
        celulas: list[Text] = [Text(token, style="bold")]
        if antes:
            celulas.append(_rotulo(antes[i] if i < len(antes) else ""))
        celulas.extend(
            [
                _rotulo(atual[i] if i < len(atual) else ""),
                _rotulo(previsto),
                Text(f"{marginal.get(previsto, float('nan')):.3f}", style="dim"),
                Text(f"{rival[:5]} {p_rival:.2f}" if rival else "", style="dim"),
            ]
        )
        tabela.add_row(*celulas)
    console.print(tabela)
    if antes:
        console.print(
            "[dim]antes = o rótulo que treinou o modelo, substituído pela "
            "reetiquetação[/dim]"
        )


def _rotulo(rotulo: str) -> Text:
    """Etiqueta BIO com a cor do tipo; vazio (sem alvo) vira um traço."""
    return Text(rotulo or "—", style=estilo_rotulo(rotulo) if rotulo else "dim")


def _rival(marginal: Mapping[str, float], previsto: str) -> tuple[str, float]:
    """Tag mais provável que não a prevista, com a probabilidade dela."""
    outros = [
        (probabilidade, tag)
        for tag, probabilidade in marginal.items()
        if tag != previsto
    ]
    if not outros:
        return "", 0.0
    probabilidade, tag = max(outros)
    return tag, probabilidade


def _alvo(detalhe: Detalhe) -> None:
    """O que a LLM diz hoje do endereço, trecho a trecho."""
    if detalhe.erro:
        console.print(f"[red]erro guardado na linha: {detalhe.erro}[/red]")
    if not detalhe.segmentos:
        console.print("[yellow]sem alvo: a linha ainda não foi etiquetada[/yellow]")
        return
    for segmento in detalhe.segmentos:
        tipo = segmento.get("tipo", "")
        estilo = estilo_tipo(tipo)
        console.print(f"  [{estilo}]{tipo:<18}[/{estilo}] {segmento.get('valor', '')}")
