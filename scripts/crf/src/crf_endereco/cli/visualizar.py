"""Comando de apresentacao: a pagina HTML que mostra o CRF lendo exemplos."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from crf_endereco import visualizacao
from crf_endereco.config import CAMINHO_DATASET


def visualizar(
    modelo: Annotated[
        Path | None,
        typer.Option("--modelo", help="tagger a visualizar (padrao: fold 0 da validacao)"),
    ] = None,
    dataset: Annotated[Path, typer.Option(help="banco de anotacao")] = CAMINHO_DATASET,
    alvo: Annotated[
        int, typer.Option("--alvo", min=1, help="quantos exemplos a pagina mostra")
    ] = visualizacao.ALVO_PADRAO,
    saida: Annotated[
        Path | None, typer.Option("--saida", help="HTML a escrever")
    ] = None,
    retreinar: Annotated[
        bool, typer.Option("--retreinar", help="ignora o modelo do fold em cache")
    ] = False,
    abrir: Annotated[bool, typer.Option("--abrir", help="abre no navegador")] = False,
) -> None:
    """Gera a pagina HTML com o CRF lendo exemplos reais do dataset.

    Sem `--modelo`, os exemplos saem do fold 0 da validacao cruzada, entao o
    modelo que os previu nunca os viu — a mesma regua do `avaliar --kfold 3`.
    Com `--modelo`, usa o tagger informado sobre o recorte de teste que o
    `treinar` gravou no banco. A escolha e por diversidade de estrutura (rural,
    parcelamento, referencia, erro...), nao por acerto.
    """
    _ = visualizacao.gerar(
        modelo=modelo,
        dataset=dataset,
        alvo=alvo,
        saida=saida,
        retreinar=retreinar,
        abrir=abrir,
    )
