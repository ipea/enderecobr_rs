"""Metricas e relatorio de avaliacao do CRF."""

from __future__ import annotations

import random
from collections import Counter, defaultdict
from collections.abc import Sequence
from pathlib import Path
from pprint import pprint

from sklearn_crfsuite import metrics

from crf_endereco.config import CAMINHO_TAGGER
from crf_endereco.modelo.crf import carregar_tagger

Features = list[list[dict[str, float]]]
Rotulos = list[list[str]]


def erros_mais_comuns_feature(
    x: Features, y_true: Rotulos, y_pred: Rotulos, n: int = 20
) -> list[tuple[tuple[str, str, str], int]]:
    """Pares (feature, rotulo real, rotulo previsto) mais frequentes nos erros."""
    errors: Counter[tuple[str, str, str]] = Counter()
    for feats, true, pred in zip(x, y_true, y_pred, strict=False):
        for i, (t, p) in enumerate(zip(true, pred, strict=False)):
            if t != p:
                errors[(str(feats[i]), f"true={t}", f"pred={p}")] += 1
    return errors.most_common(n)


def erros_mais_comuns_token(
    x: Features, y_true: Rotulos, y_pred: Rotulos, n: int = 20
) -> list[tuple[tuple[str, str, str], int]]:
    """Tokens que mais aparecem mal classificados."""
    errors: Counter[tuple[str, str, str]] = Counter()
    for feats, true, pred in zip(x, y_true, y_pred, strict=False):
        for i, (t, p) in enumerate(zip(true, pred, strict=False)):
            if t != p:
                token_atual = [f[2:] for f in feats[i] if f.startswith("0:")]
                if token_atual:
                    errors[(str(token_atual[0]), f"true={t}", f"pred={p}")] += 1
    return errors.most_common(n)


def amostra_erros(
    tokens: Rotulos,
    y_true: Rotulos,
    y_pred: Rotulos,
    n: int = 10,
    classes: Sequence[str] = (),
) -> list[tuple[list[str], list[str], list[str]]]:
    """Trechos com ao menos um erro (opcionalmente so das `classes` dadas)."""
    erros: list[tuple[list[str], list[str], list[str]]] = []
    for toks, true, pred in zip(tokens, y_true, y_pred, strict=False):
        for t, p in zip(true, pred, strict=False):
            if t != p and (not classes or t in classes or p in classes):
                erros.append((toks, true, pred))
                break
    random.shuffle(erros)
    return erros[:n]


def acuracia_labels(
    y_true: Rotulos, y_pred: Rotulos, labels: Sequence[str]
) -> tuple[int, int]:
    """Acertos e total restritos aos rotulos de `labels`."""
    total = 0
    acertos = 0
    for true, pred in zip(y_true, y_pred, strict=False):
        for t, p in zip(true, pred, strict=False):
            if t not in labels and p not in labels:
                continue
            total += 1
            acertos += int(t == p)
    return acertos, total


def acuracia_proporcional(y_true: Rotulos, y_pred: Rotulos) -> float:
    """Media, por trecho, da fracao de tokens corretos."""
    proporcoes = []
    for true, pred in zip(y_true, y_pred, strict=False):
        acertos = sum(1 for t, p in zip(true, pred, strict=False) if t == p)
        proporcoes.append(acertos / len(true))
    return sum(proporcoes) / len(proporcoes)


def erros_mais_comuns_por_categoria(
    x: Features, y_true: Rotulos, y_pred: Rotulos, categorias: Rotulos, n: int = 20
) -> list[tuple[tuple[tuple[str, str], str], int]]:
    """Trocas de rotulo (real, previsto) mais frequentes por categoria."""
    errors: Counter[tuple[tuple[str, str], str]] = Counter()
    for _feats, true, pred, cats in zip(x, y_true, y_pred, categorias, strict=False):
        dif_tags = {(t, p) for t, p in zip(true, pred, strict=False) if t != p}
        for dif in dif_tags:
            for c in cats:
                errors[(dif, c)] += 1
    return errors.most_common(n)


def acuracia_completa_por_categoria(
    y_true: Rotulos, y_pred: Rotulos, categorias: Rotulos
) -> None:
    """Acuracia de trecho inteiro, quebrada por cada coluna de `categorias`."""
    for categoria_pos in range(len(categorias[0])):
        cat_dict: dict[str, tuple[Rotulos, Rotulos]] = defaultdict(lambda: ([], []))

        for y_t, y_p, cs in zip(y_true, y_pred, categorias, strict=False):
            categoria = cs[categoria_pos]
            cat_dict[categoria][0].append(y_t)
            cat_dict[categoria][1].append(y_p)

        resultado = [
            (
                categoria,
                metrics.sequence_accuracy_score(dados[0], dados[1]),
                acuracia_proporcional(dados[0], dados[1]),
            )
            for categoria, dados in cat_dict.items()
        ]
        resultado.sort(key=lambda item: item[1], reverse=True)

        for cat, acc_total, acc_prop in resultado:
            print(f"{cat:<15} | {100.0 * acc_total:.2f} | {100.0 * acc_prop:.2f}")
        print()


def show(sent: Sequence[str], y_true: Sequence[str], y_pred: Sequence[str]) -> None:
    """Imprime um trecho com o rotulo real e o previsto lado a lado."""
    if len(sent) == 0:
        return
    max_len = max(len(token) for token in sent) + 2
    print(f"{'String':<{max_len}} {'Target':<10} {'Predito':<10}")
    print("----------------------------------")
    for s, t, p in zip(sent, y_true, y_pred, strict=False):
        print(f"{s:<{max_len}} {t:<10} {p:<10}")
    print("################################")


def pares_de_rotulos(y: Rotulos) -> list[tuple[str, ...]]:
    """Agrupa os rotulos por tipo (`B_logradouro`/`I_logradouro` -> um par)."""
    pares: dict[str, set[str]] = defaultdict(set)
    for y_i in y:
        for y_token in y_i:
            if "_" in y_token:
                pos_bio, tipo = y_token.split("_", 1)
                pares[tipo].add(pos_bio)
            else:
                pares[y_token] = set()
    return [
        (tipo,) if not bios else tuple(sorted(f"{bio}_{tipo}" for bio in bios))
        for tipo, bios in pares.items()
    ]


def avaliar(
    x: Features,
    y: Rotulos,
    categorias: Rotulos,
    tokens: Rotulos,
    tagger: Path = CAMINHO_TAGGER,
) -> None:
    """Relatorio completo: token, classe, categoria e amostras de erro."""
    print("Executando modelo...")
    crf = carregar_tagger(tagger)
    # predict() devolve ndarray de rotulos; a conversao abaixo e so o
    # recorte para a estrutura que o relatorio consome.
    y_pred: Rotulos = [[str(tag) for tag in linha] for linha in crf.predict(x)]

    print(metrics.flat_classification_report(y, y_pred, zero_division=0.0))
    print(f"Acurácia no trecho completo: {metrics.sequence_accuracy_score(y, y_pred)}")
    print(f"Acurácia proporcional: {acuracia_proporcional(y, y_pred)}")
    print()

    rotulos = pares_de_rotulos(y)
    for rotulo in rotulos:
        acertos, total = acuracia_labels(y, y_pred, rotulo)
        print(f"Acurácia de {rotulo}: {acertos}/{total} = {acertos / total:.2}")

    print()
    print("Acurácia Completa por categorias:")
    acuracia_completa_por_categoria(y, y_pred, categorias)

    print()
    print("Erros Token:")
    pprint(erros_mais_comuns_token(x, y, y_pred))
    print()
    print("Erros Features:")
    pprint(erros_mais_comuns_feature(x, y, y_pred))
    print()
    print("Erros Categorias:")
    pprint(erros_mais_comuns_por_categoria(x, y, y_pred, categorias))

    print()
    for rotulo in rotulos:
        print(f"Amostra de Erros de {rotulo!s}")
        for caso in amostra_erros(tokens, y, y_pred, n=5, classes=list(rotulo)):
            show(*caso)
