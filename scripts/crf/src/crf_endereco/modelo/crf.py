"""CRF de enderecos: dados de treino, treino, tuning e inferencia."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import sklearn_crfsuite
import typer
from sklearn.metrics import make_scorer
from sklearn.model_selection import GridSearchCV, ShuffleSplit, train_test_split
from sklearn_crfsuite.metrics import flat_accuracy_score, flat_classification_report

from crf_endereco.config import CAMINHO_DATASET, CAMINHO_TAGGER
from crf_endereco.dataset import carregar_anotados, segmentos_de
from crf_endereco.features import ExtratorFeature, tokenize, tokenize_com_offsets
from crf_endereco.rotulos import mergear

# \`str.isspace()\` é mais amplo que o \`u8::is_ascii_whitespace\` usado pelo Rust
# (inclui NBSP, por exemplo); o conjunto explícito mantém as duas
# implementações equivalentes.
ESPACOS_ASCII = frozenset(" \t\n\x0c\r")


@dataclass(frozen=True)
class Exemplos:
    """Dataset pronto para o CRF: features, rotulos, tokens e categorias."""

    x: list[list[dict[str, float]]]
    y: list[list[str]]
    tokens: list[list[str]]
    categorias: list[list[str]]


def carregar_exemplos(caminho: Path = CAMINHO_DATASET) -> Exemplos:
    """Le o dataset etiquetado e monta features/rotulos.

    E o unico caminho de dados do modelo: treino, busca de hiperparametros e
    avaliacao usam exatamente as mesmas linhas, features e etiquetas.
    """
    extrator = ExtratorFeature()
    x: list[list[dict[str, float]]] = []
    y: list[list[str]] = []
    tokens: list[list[str]] = []
    categorias: list[list[str]] = []

    print("Preprocessando dados...")
    for exemplo in carregar_anotados(caminho):
        toks, labels = mergear(exemplo.endereco, segmentos_de(exemplo), tokenize)
        x.append(extrator.tokens2features(toks))
        y.append(labels)
        tokens.append(toks)
        categorias.append([exemplo.origem, exemplo.uf])

    return Exemplos(x=x, y=y, tokens=tokens, categorias=categorias)


def treinar(
    dataset: Path = CAMINHO_DATASET,
    saida: Path = CAMINHO_TAGGER,
    fracao_teste: float = 0.1,
) -> None:
    """Treina o CRF e reporta a acuracia na fracao de teste."""
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

    print(f"Acurácia: {flat_accuracy_score(y_test, y_pred):.2f}")
    print(flat_classification_report(y_test, y_pred, zero_division=0.0))


def tunar() -> None:
    """Busca de hiperparametros sobre o mesmo dataset, features e etiquetas."""
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


def carregar_tagger(caminho: Path = CAMINHO_TAGGER) -> sklearn_crfsuite.CRF:
    """Carrega o CRF treinado, com erro claro quando o arquivo nao existe."""
    if not caminho.is_file():
        raise typer.BadParameter(
            f"tagger nao encontrado: {caminho}\n"
            + "treine com `uv run crf treinar` ou passe --tagger"
        )
    return sklearn_crfsuite.CRF(model_filename=str(caminho))


def montar_segmentos(
    frase: str,
    tokens_com_offset: list[tuple[str, int]],
    tags: list[str],
) -> list[dict[str, str]]:
    """Remonta os segmentos a partir dos rotulos BIO.

    Espelha `SeparadorEndereco::segmentar` do Rust (`src/separador_endereco.rs`):
    o separador entre tokens de um mesmo segmento vem do texto bruto, ou seja,
    so entra um espaco quando o caractere anterior ao token e espaco em branco.
    Assim "S/N" e "310A" continuam verbatim em vez de virar "S / N" e "310 A".
    """
    segmentos: list[dict[str, str]] = []

    for (tok, offset), tag in zip(tokens_com_offset, tags, strict=True):
        partes = tag.split("_", 1)
        if len(partes) != 2:
            continue  # "O": token fora de qualquer segmento

        bio, tipo = partes
        tipo = tipo.lower()

        if bio == "B":
            segmentos.append({"tipo": tipo, "valor": tok})
        elif bio == "I":
            if not segmentos or segmentos[-1]["tipo"] != tipo:
                continue
            if offset > 0 and frase[offset - 1] in ESPACOS_ASCII:
                segmentos[-1]["valor"] += " "
            segmentos[-1]["valor"] += tok

    return segmentos


def segmentar(
    crf: sklearn_crfsuite.CRF, extrator: ExtratorFeature, frase: str
) -> list[dict[str, str]]:
    """Pipeline completo do Rust (`segmentar_endereco`) para uma frase."""
    tokens_com_offset = tokenize_com_offsets(frase)
    x = extrator.tokens2features([tok for tok, _ in tokens_com_offset])
    tags = crf.predict_single(x)

    return montar_segmentos(frase, tokens_com_offset, tags)
