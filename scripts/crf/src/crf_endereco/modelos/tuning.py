"""Busca de hiperparametros do CRF."""

import sklearn_crfsuite
from sklearn.metrics import make_scorer
from sklearn.model_selection import GridSearchCV, ShuffleSplit
from sklearn_crfsuite.metrics import flat_accuracy_score

from crf_endereco.modelos.treino import carregar_exemplos


def tunar() -> None:
    """Roda o GridSearch sobre o mesmo dataset, etiquetagem e features do treino."""
    exemplos = carregar_exemplos()

    crf = sklearn_crfsuite.CRF(
        algorithm="lbfgs",
        max_iterations=500,
        all_possible_transitions=False,
        min_freq=2,
        verbose=False,
    )
    busca = GridSearchCV(
        crf,
        param_grid={"c1": [0.0, 0.1, 0.25, 1.0], "c2": [0.1, 0.25, 0.5, 1.0]},
        cv=ShuffleSplit(n_splits=1, test_size=0.1, random_state=42),
        verbose=3,
        n_jobs=13,
        scoring=make_scorer(flat_accuracy_score),
        refit=True,
    )
    _ = busca.fit(exemplos.x, exemplos.y)

    print("best params:", busca.best_params_)
    print("best CV score:", busca.best_score_)
    print(f"model size: {busca.best_estimator_.size_ / 1_000_000:0.2f}M")
