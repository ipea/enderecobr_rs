import sklearn_crfsuite
from sklearn.metrics import make_scorer
from sklearn.model_selection import GridSearchCV, ShuffleSplit
from sklearn_crfsuite.metrics import flat_accuracy_score

from crf_endereco.treinamento import carregar_dados


def main():
    # Mesmo dataset, etiquetagem e features do `treinamento.py`.
    x, y = carregar_dados()

    crf = sklearn_crfsuite.CRF(
        algorithm="lbfgs",
        max_iterations=100,
        all_possible_transitions=False,
        min_freq=5,
        verbose=False,
    )

    scorer = make_scorer(flat_accuracy_score)
    dataset_splitter = ShuffleSplit(n_splits=1, test_size=0.1, random_state=42)

    # Experimental
    # from sklearn.experimental import enable_halving_search_cv
    # from sklearn.model_selection import HalvingRandomSearchCV
    # params_space = {
    #     "c1": scipy.stats.expon(scale=0.5),
    #     "c2": scipy.stats.expon(scale=0.05),
    # }
    # random_search = HalvingRandomSearchCV(
    #     crf,
    #     params_space,
    #     cv=dataset_splitter,
    #     verbose=3,
    #     n_jobs=-1,
    #     scoring=scorer,
    #     n_candidates=100,
    #     return_train_score=True,
    #     max_resources=1000,
    #     min_resources="exhaust",
    #     resource="max_iterations",
    # )
    random_search = GridSearchCV(
        crf,
        param_grid={
            "c1": [0.1, 0.25, 0.5, 0.75, 1.0],
            "c2": [0.1, 0.25, 0.5, 0.75, 1.0],
        },
        cv=dataset_splitter,
        verbose=3,
        n_jobs=13,
        scoring=scorer,
        refit=True,
    )
    _ = random_search.fit(x, y)

    print(f"Results: {random_search.cv_results_!s}")
    print("best params:", random_search.best_params_)
    print("best CV score:", random_search.best_score_)
    print(f"model size: {random_search.best_estimator_.size_ / 1_000_000:0.2f}M")


if __name__ == "__main__":
    main()
