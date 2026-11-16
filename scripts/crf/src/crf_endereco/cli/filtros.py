"""Opções de recorte compartilhadas por `etiquetar lote` e `explorar`.

Os dois comandos olham o mesmo dataset pelas mesmas lentes: UF, município,
origem, trecho, lote — e pelos mesmos filtros de previsão do CRF (tipo previsto,
faixa de confiança, divergência do próprio rótulo). As flags ficam declaradas
aqui, como aliases `Annotated`, para que as duas listas de opções não divirjam:
este é o único lugar onde os nomes e as mensagens de ajuda existem. A montagem
de `Filtros` e a passada do modelo também, porque um comando de leitura e um de
escrita precisam concordar sobre o que é "o mesmo recorte".
"""

from __future__ import annotations

import sqlite3
from collections import Counter
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path
from typing import Annotated

import typer
from rich import box
from rich.table import Table
from rich.text import Text

from crf_endereco.anotacao.filtro_crf import (
    Divergencia,
    Faixa,
    Previsao,
    descrever_faixa,
    divergencias,
    filtrar_por_confianca,
    filtrar_por_tipos,
    prever,
)
from crf_endereco.anotacao.lote import dividir_filtros
from crf_endereco.anotacao.pendentes import Filtros, Pendente, pendentes
from crf_endereco.dataset import ler_recorte
from crf_endereco.modelo.crf import (
    carregar_exemplos,
    carregar_tagger,
    nome_do_modelo,
    separar_por_recorte,
)
from crf_endereco.rotulos import CONCORDA_COM_O_CRF, ROTULO_MANTIDO, ROTULO_NOVO
from crf_endereco.ui import console, estilo_rotulo

# Como cada veredito da reetiquetacao aparece (ver `rotulos.comparar`).
ESTILO_VEREDITO = {
    CONCORDA_COM_O_CRF: "green",
    ROTULO_MANTIDO: "yellow",
    ROTULO_NOVO: "cyan",
}

# Trocas mostradas por endereco na linha de resumo (as demais viram `+n`).
TROCAS_POR_ENDERECO = 3
# Pares real -> previsto listados no topo da revisao por divergencia.
TOPO_CONFUSOES = 10

OpcaoLote = Annotated[
    str | None,
    typer.Option("--lote", help="Filtra as linhas por lote (coluna `lote`)."),
]
OpcaoUf = Annotated[
    list[str] | None,
    typer.Option("--uf", help="Filtra por UF (repita ou separe por vírgula)."),
]
OpcaoMunicipio = Annotated[
    list[str] | None,
    typer.Option(
        "--municipio", help="Filtra por município (repita ou separe por vírgula)."
    ),
]
OpcaoOrigem = Annotated[
    list[str] | None,
    typer.Option("--origem", help="Filtra por origem (repita ou separe por vírgula)."),
]
OpcaoBusca = Annotated[
    list[str] | None,
    typer.Option(
        "--busca",
        help=(
            "Recorta pelos endereços que contêm algum destes trechos (LIKE "
            "'%trecho%', ignorando caixa e acentos; repita para unir em OU)."
        ),
    ),
]
OpcaoApenasTipos = Annotated[
    list[str] | None,
    typer.Option(
        "--apenas-tipos",
        help=(
            "Só endereços em que o CRF prevê ao menos um destes tipos (repita ou "
            "separe por vírgula). O modelo roda em todo o recorte antes."
        ),
    ),
]
OpcaoIncertos = Annotated[
    str | None,
    typer.Option(
        "--incertos",
        help=(
            "Só endereços em que o CRF está em dúvida: algum token com "
            "probabilidade prevista em [mínimo, máximo) — `0.6,0.8`; um valor só "
            "(`0.8`) vale como máximo, com mínimo 0. O modelo roda em todo o "
            "recorte antes."
        ),
    ),
]
OpcaoIncertosMedia = Annotated[
    str | None,
    typer.Option(
        "--incertos-media",
        help=(
            "Como --incertos, mas pela média: endereço cuja média geométrica das "
            "probabilidades previstas, token a token, cai na faixa `mínimo,máximo`."
        ),
    ),
]
OpcaoModelo = Annotated[
    Path,
    typer.Option(
        "--modelo",
        help="CRF usado nos filtros de previsão (padrão: o tagger treinado).",
    ),
]
OpcaoBalancear = Annotated[
    bool,
    typer.Option(
        "--balancear/--sem-balancear",
        help="Sorteia o recorte alternando entre células (UF, origem) e priorizando "
        "as menos anotadas; desligado, só sorteia.",
    ),
]
OpcaoIncluirRevisados = Annotated[
    bool,
    typer.Option(
        "--incluir-revisados",
        help=(
            "Com --divergentes, inclui quem já foi reetiquetado por este modelo "
            "(por padrão a linha revista fica de fora)."
        ),
    ),
]
OpcaoLimite = Annotated[
    int | None,
    typer.Option("--limite", "-l", min=1, help="Considera no máximo N linhas."),
]


def montar_filtros(
    *,
    lote: str | None = None,
    uf: list[str] | None = None,
    municipio: list[str] | None = None,
    origem: list[str] | None = None,
    busca: list[str] | None = None,
    balancear: bool = True,
    anotados: bool = False,
    incluir_erros: bool = False,
    apenas_erros: bool = False,
    revisados: bool = False,
) -> Filtros:
    """`Filtros` a partir das flags: valores repetidos/CSV viram uma lista limpa."""
    return Filtros(
        lote=lote,
        incluir_erros=incluir_erros,
        apenas_erros=apenas_erros,
        anotados=anotados,
        revisados=revisados,
        busca=busca,
        ufs=dividir_filtros(uf),
        origens=dividir_filtros(origem),
        municipios=dividir_filtros(municipio),
        balancear=balancear,
    )


def precisa_do_crf(
    tipos: frozenset[str],
    faixa_incertos: Faixa | None,
    faixa_media: Faixa | None,
    *,
    divergentes: bool = False,
) -> bool:
    """Se o recorte depende de rodar o modelo antes de saber quais linhas sobram."""
    return (
        bool(tipos)
        or faixa_incertos is not None
        or faixa_media is not None
        or divergentes
    )


def prever_recorte(linhas: Sequence[Pendente], modelo: Path) -> list[Previsao]:
    """Roda o CRF no recorte inteiro uma vez: é o que sustenta todos os filtros."""
    console.print(
        f"[dim]Prevendo {len(linhas)} endereço(s) com o CRF {modelo.name}…[/dim]"
    )
    return prever(linhas, modelo)


def filtrar_por_previsao(
    filtros: Filtros,
    previsoes: Sequence[Previsao],
    *,
    tipos: frozenset[str],
    faixa_incertos: Faixa | None,
    faixa_media: Faixa | None,
) -> Filtros:
    """Recorta `filtros` pelos tipos previstos e pelas faixas de confiança."""
    aprovados: frozenset[int] | None = None
    if tipos:
        por_tipo = filtrar_por_tipos(previsoes, tipos)
        aprovados = por_tipo if aprovados is None else aprovados & por_tipo
        console.print(
            f"[dim]Filtro por tipo: {len(por_tipo)} de {len(previsoes)} "
            "endereço(s) com ao menos um tipo previsto.[/dim]"
        )
    if faixa_incertos is not None:
        por_menor = filtrar_por_confianca(previsoes, faixa_incertos)
        aprovados = por_menor if aprovados is None else aprovados & por_menor
        console.print(
            f"[dim]Filtro por incerteza: {len(por_menor)} de {len(previsoes)} "
            f"endereço(s) com algum token em {descrever_faixa(faixa_incertos)}.[/dim]"
        )
    if faixa_media is not None:
        por_media = filtrar_por_confianca(previsoes, faixa_media, media=True)
        aprovados = por_media if aprovados is None else aprovados & por_media
        console.print(
            f"[dim]Filtro por incerteza média: {len(por_media)} de "
            f"{len(previsoes)} endereço(s) com média em "
            f"{descrever_faixa(faixa_media)}.[/dim]"
        )
    return filtros if aprovados is None else replace(filtros, ids=aprovados)


def recortar_recorte(
    conn: sqlite3.Connection, filtros: Filtros, modelo: Path, papel: str | None
) -> Filtros:
    """Restringe aos hashes do papel pedido (`treino` ou `teste`) do modelo.

    `None` desliga. Um `treino` que o modelo viu é onde o erro dele aponta
    rótulo suspeito; um `teste` que ele nunca viu é onde o erro aponta falta de
    generalização.
    """
    if papel is None:
        return filtros
    hashes = ler_recorte(conn, nome_do_modelo(modelo))[papel]
    if not hashes:
        raise typer.BadParameter(
            f"recorte '{papel}' não gravado para {modelo.name}: treine com "
            "`crf treinar` antes de recortar por papel."
        )
    recortado = hashes if filtros.hashes is None else filtros.hashes & hashes
    return replace(filtros, hashes=frozenset(recortado))


def recortar_divergentes(
    conn: sqlite3.Connection,
    filtros: Filtros,
    banco: Path,
    modelo: Path,
    *,
    incluir_revisados: bool,
) -> tuple[Filtros, dict[str, Divergencia]]:
    """Recorta o recorte no que o modelo erra mesmo tendo treinado com o rótulo.

    A divergência é o sinal de rótulo suspeito: o modelo viu aquele endereço no
    treino, então errar ali não é falta de generalização. Devolve os filtros
    apontando para as linhas já anotadas desse recorte e as divergências por
    hash: elas levam o rótulo do treino e o previsto até a hora de comparar com
    a resposta nova da LLM.
    """
    nome = nome_do_modelo(modelo)
    recorte = ler_recorte(conn, nome)["treino"]
    if not recorte:
        raise typer.BadParameter(
            f"recorte de treino não gravado para {modelo.name}: treine com "
            "`crf treinar` antes de revisar por divergência."
        )

    candidatas = pendentes(
        conn,
        replace(
            filtros,
            hashes=recorte,
            anotados=True,
            pular_revisados_por=None if incluir_revisados else nome,
        ),
    )
    if not candidatas:
        console.print("[yellow]Nenhum endereço do treino para revisar.[/yellow]")
        return replace(filtros, hashes=frozenset(), anotados=True), {}

    console.print(
        f"[dim]Prevendo {len(candidatas)} endereço(s) do recorte de treino de "
        f"{nome}…[/dim]"
    )
    treino, _ = separar_por_recorte(
        carregar_exemplos(banco),
        {"treino": {linha.hash for linha in candidatas}, "teste": set()},
    )
    achados = divergencias(carregar_tagger(modelo), treino)
    console.print(
        f"[bold]{len(achados)}[/bold]/{len(candidatas)} endereço(s) do treino de "
        f"{nome} divergem do rótulo "
        f"({100 * len(achados) / len(candidatas):.1f}%)."
    )
    imprimir_confusoes(achados)
    return (
        replace(
            filtros, hashes=frozenset(achado.hash for achado in achados), anotados=True
        ),
        {achado.hash: achado for achado in achados},
    )


def imprimir_confusoes(achados: Sequence[Divergencia]) -> None:
    """Pares real → previsto que o modelo troca, do mais frequente ao menos."""
    confusoes = Counter(par for achado in achados for par in achado.pares)
    if not confusoes:
        console.print("[green]O modelo acerta o rótulo de todo o treino.[/green]")
        return

    tabela = Table(box=box.SIMPLE_HEAD, pad_edge=False, show_edge=False)
    tabela.add_column("esperado")
    tabela.add_column("previsto")
    tabela.add_column("tokens", justify="right", style="dim")
    for (esperado, previsto), vezes in confusoes.most_common(TOPO_CONFUSOES):
        tabela.add_row(
            Text(esperado, style="yellow"),
            Text(previsto, style=estilo_rotulo(previsto)),
            str(vezes),
        )
    console.print(tabela)


def pares_abreviados(pares: Sequence[tuple[str, str]]) -> str:
    """`I_LOG→I_LOC B_LOG→O +2`: rótulo abreviado em 5 caracteres para caber."""
    mostradas = " ".join(
        f"{esperado[:5]}→{previsto[:5]}"
        for esperado, previsto in pares[:TROCAS_POR_ENDERECO]
    )
    resto = len(pares) - TROCAS_POR_ENDERECO
    return f"{mostradas} +{resto}" if resto > 0 else mostradas
