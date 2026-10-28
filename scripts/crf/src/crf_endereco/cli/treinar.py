"""Comando de treino do CRF."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import sklearn_crfsuite
import sklearn_crfsuite.metrics
import typer
from sklearn.model_selection import train_test_split

from crf_endereco.config import CAMINHO_DATASET, CAMINHO_TAGGER
from crf_endereco.modelos.treino import carregar_exemplos


def treinar(
    dataset: Annotated[Path, typer.Option(help="banco de anotacao")] = CAMINHO_DATASET,
    saida: Annotated[Path, typer.Option(help="tagger a escrever")] = CAMINHO_TAGGER,
    fracao_teste: Annotated[
        float, typer.Option(help="fracao separada para teste")
    ] = 0.1,
) -> None:
    """Treina o CRF sobre o dataset anotado."""
    exemplos = carregar_exemplos(dataset)
    x_train, x_test, y_train, y_test = train_test_split(
        exemplos.x, exemplos.y, test_size=fracao_teste, random_state=42
    )

    print(f"Realizando treinamento (n={len(x_train)})...")
    saida.parent.mkdir(parents=True, exist_ok=True)
    crf = sklearn_crfsuite.CRF(
        algorithm="lbfgs",
        c1=0.1,
        c2=0.2,
        verbose=True,
        max_iterations=5_000,
        all_possible_transitions=False,
        min_freq=2,
        model_filename=str(saida),
    )
    modelo = crf.fit(x_train, y_train)
    y_pred = modelo.predict(x_test)

    print(
        f"Acurácia: {sklearn_crfsuite.metrics.flat_accuracy_score(y_test, y_pred):.2f}"
    )
    print(
        sklearn_crfsuite.metrics.flat_classification_report(
            y_test, y_pred, zero_division=0.0
        )
    )
