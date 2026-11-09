"""Comandos do modelo: treinar, tunar, avaliar, segmentar, diferencial, inspecionar."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Annotated

import typer

from crf_endereco.config import CAMINHO_DATASET, CAMINHO_TAGGER
from crf_endereco.dataset import carregar_anotados
from crf_endereco.features import ExtratorFeature
from crf_endereco.modelo import crf as modelo_crf
from crf_endereco.modelo import relatorio
from crf_endereco.segmentador_rust import rodar_segmentacao

OpcaoDataset = Annotated[Path, typer.Option(help="banco de anotacao")]
OpcaoTagger = Annotated[Path, typer.Option(help="tagger treinado")]
OpcaoEstratificar = Annotated[
    str,
    typer.Option(help="estratificacao do split: origem, origem_uf ou nenhum."),
]


def treinar(
    dataset: OpcaoDataset = CAMINHO_DATASET,
    saida: Annotated[Path, typer.Option(help="tagger a escrever")] = CAMINHO_TAGGER,
    fracao_teste: Annotated[
        float, typer.Option(help="fracao separada para teste")
    ] = 0.1,
    estratificar_por: OpcaoEstratificar = "origem",
    com_aumento: Annotated[
        bool, typer.Option("--com-aumento", help="treina tambem sem pontuacao")
    ] = False,
    c1: Annotated[
        float, typer.Option("--c1", help="Regularizacao L1 do CRF.")
    ] = modelo_crf.C1_TREINO,
    c2: Annotated[
        float, typer.Option("--c2", help="Regularizacao L2 do CRF.")
    ] = modelo_crf.C2_TREINO,
    max_iteracoes: Annotated[
        int, typer.Option("--max-iteracoes", min=1, help="Iteracoes do L-BFGS.")
    ] = modelo_crf.MAX_ITERACOES_TREINO,
    min_freq: Annotated[
        int,
        typer.Option("--min-freq", min=1, help="Frequencia minima de uma feature."),
    ] = modelo_crf.MIN_FREQ_TREINO,
    verboso: Annotated[
        bool,
        typer.Option("--verboso/--sem-verboso", help="Log de convergencia do L-BFGS."),
    ] = modelo_crf.VERBOSE_TREINO,
    semente: Annotated[
        int, typer.Option("--semente", help="Semente do split treino/teste.")
    ] = modelo_crf.SEMENTE_SPLIT,
) -> None:
    """Treina o CRF sobre o dataset anotado."""
    modelo_crf.treinar(
        dataset,
        saida,
        fracao_teste,
        estratificar_por=estratificar_por,
        com_aumento=com_aumento,
        c1=c1,
        c2=c2,
        max_iteracoes=max_iteracoes,
        min_freq=min_freq,
        verboso=verboso,
        semente=semente,
    )


def tunar(
    c1: Annotated[
        list[float],
        typer.Option("--c1", help="Valores de c1 testados (repita para testar mais)."),
    ] = modelo_crf.GRADE_C1,
    c2: Annotated[
        list[float],
        typer.Option("--c2", help="Valores de c2 testados (repita para testar mais)."),
    ] = modelo_crf.GRADE_C2,
    max_iteracoes: Annotated[
        int, typer.Option("--max-iteracoes", min=1, help="Iteracoes do L-BFGS por fit.")
    ] = modelo_crf.MAX_ITERACOES_TUNING,
    min_freq: Annotated[
        int,
        typer.Option("--min-freq", min=1, help="Frequencia minima de uma feature."),
    ] = modelo_crf.MIN_FREQ_TUNING,
    n_jobs: Annotated[
        int, typer.Option("--n-jobs", help="Fits rodando em paralelo.")
    ] = modelo_crf.N_JOBS_TUNING,
    semente: Annotated[
        int, typer.Option("--semente", help="Semente do split de validacao.")
    ] = modelo_crf.SEMENTE_TUNING,
    fracao_validacao: Annotated[
        float,
        typer.Option(
            "--fracao-validacao", min=0.0, max=1.0, help="Fracao separada para validacao."
        ),
    ] = modelo_crf.FRACAO_VALIDACAO_TUNING,
    verboso: Annotated[
        int, typer.Option("--verboso", min=0, help="Nivel de log da busca.")
    ] = modelo_crf.VERBOSE_TUNING,
    com_aumento: Annotated[
        bool,
        typer.Option(
            "--com-aumento",
            help="Tuna tambem com as variantes sem pontuacao (vazam entre os folds).",
        ),
    ] = False,
    estratificar_por: OpcaoEstratificar = "origem",
) -> None:
    """Busca hiperparametros do CRF."""
    modelo_crf.tunar(
        c1,
        c2,
        max_iteracoes,
        min_freq,
        n_jobs,
        semente,
        fracao_validacao,
        verboso,
        com_aumento,
        estratificar_por,
    )


def avaliar(
    dataset: OpcaoDataset = CAMINHO_DATASET,
    tagger: OpcaoTagger = CAMINHO_TAGGER,
    fracao_teste: Annotated[
        float, typer.Option(help="mesma fracao de teste usada no treino")
    ] = 0.1,
    estratificar_por: OpcaoEstratificar = "origem",
    semente: Annotated[
        int, typer.Option("--semente", help="mesma semente de split usada no treino")
    ] = modelo_crf.SEMENTE_SPLIT,
) -> None:
    """Avalia o CRF no recorte de teste do treino, nunca no dataset inteiro."""
    exemplos = modelo_crf.carregar_exemplos(dataset)
    _, teste = modelo_crf.dividir(
        exemplos, fracao_teste, semente, estratificar_por=estratificar_por
    )
    relatorio.avaliar(teste.x, teste.y, teste.categorias, teste.tokens, tagger)


def segmentar(tagger: OpcaoTagger = CAMINHO_TAGGER) -> None:
    """Segmenta enderecos lidos do stdin."""
    crf = modelo_crf.carregar_tagger(tagger)
    extrator = ExtratorFeature()

    while True:
        try:
            linha = input()
        except EOFError:
            break
        if not linha:
            continue
        print("-----------------")
        for segmento in modelo_crf.segmentar(crf, extrator, linha):
            print(f"{segmento.get('tipo', '').title()}: {segmento.get('valor', '')}")


def diferencial(
    dataset: Annotated[
        Path, typer.Argument(help="banco de anotacao")
    ] = CAMINHO_DATASET,
    tagger: OpcaoTagger = CAMINHO_TAGGER,
) -> None:
    """Compara a segmentacao do CRF em Python e no binario Rust.

    As duas versoes precisam usar o mesmo modelo, senao a comparacao mistura
    diferenca de features com diferenca de treino.
    """
    crf = modelo_crf.carregar_tagger(tagger)
    extrator = ExtratorFeature()
    enderecos = [exemplo.endereco for exemplo in carregar_anotados(dataset)]

    segmentos_python = [
        modelo_crf.segmentar(crf, extrator, endereco) for endereco in enderecos
    ]
    saida_rust = rodar_segmentacao(enderecos, modelo=tagger)

    diferentes = 0
    for endereco, bruto, segmentos in zip(
        enderecos, saida_rust, segmentos_python, strict=True
    ):
        try:
            segmentos_rust = json.loads(bruto).get("segmentos", [])
        except json.JSONDecodeError as erro:
            raise typer.BadParameter(
                f"o segmentador devolveu JSON invalido para {endereco!r}: {erro}"
            ) from erro
        if segmentos_rust == segmentos:
            continue
        diferentes += 1
        print("-------------")
        print(endereco, "\n")
        print("[Python]")
        _printa(segmentos)
        print("\n[Rust]")
        _printa(segmentos_rust)

    print("------")
    print(f"Total Casos Diferentes: {diferentes}/{len(enderecos)}")


def inspecionar(
    tagger: Annotated[Path, typer.Argument(help="Path do tagger treinado")] = (
        CAMINHO_TAGGER
    ),
    output: Annotated[
        Path | None, typer.Option("--output", "-o", help="Path do resultado")
    ] = None,
) -> None:
    """Lista os pesos aprendidos por atributo e rotulo."""
    crf = modelo_crf.carregar_tagger(tagger)
    linhas = [
        f"{weight:0.6f} {label:<8} {attr}\n"
        for (attr, label), weight in Counter(crf.state_features_).most_common()
    ]
    if output is None:
        print("".join(linhas), end="")
        return
    try:
        _ = output.write_text("".join(linhas), encoding="utf-8")
    except OSError as erro:
        raise typer.BadParameter(
            f"nao foi possivel escrever {output}: {erro}"
        ) from erro


def _printa(segmentos: list[dict[str, str]]) -> None:
    for segmento in segmentos:
        print(f"  {segmento['tipo']:<20} {segmento['valor']}")
