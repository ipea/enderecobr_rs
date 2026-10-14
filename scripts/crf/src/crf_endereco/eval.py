import json
import random
import sqlite3
from collections import Counter, defaultdict
from pprint import pprint

import duckdb
import sklearn_crfsuite
from sklearn_crfsuite import metrics

from crf_endereco.preproc import ExtratorFeature, tokenize
from crf_endereco.treinamento import mergear


def erros_mais_comuns_feature(x, y_true, y_pred, n=20):
    errors = Counter()
    for feats, true, pred in zip(x, y_true, y_pred):
        for i, (t, p) in enumerate(zip(true, pred)):
            if t != p:
                errors[(str(feats[i]), f"true={t}", f"pred={p}")] += 1
    return errors.most_common(n)


def erros_mais_comuns_token(x, y_true, y_pred, n=20):
    errors = Counter()
    for feats, true, pred in zip(x, y_true, y_pred):
        for i, (t, p) in enumerate(zip(true, pred)):
            if t != p:
                token_atual = [f[2:] for f in feats[i] if f.startswith("0:")]
                if len(token_atual):
                    errors[(str(token_atual[0]), f"true={t}", f"pred={p}")] += 1
    return errors.most_common(n)


def amostra_erros(tokens, y_true, y_pred, n=10, classes: list[str] = []):
    erros = []
    for toks, true, pred in zip(tokens, y_true, y_pred):
        for t, p in zip(true, pred):
            if t != p and (len(classes) == 0 or t in classes or p in classes):
                erros.append((toks, true, pred))
                break

    random.shuffle(erros)
    return erros[:n]


def acuracia_labels(y_true, y_pred, labels):
    n = 0
    acertos = 0
    for true, pred in zip(y_true, y_pred):
        for t, p in zip(true, pred):
            if t not in labels and p not in labels:
                continue
            n += 1
            if t == p:
                acertos += 1

    return acertos, n


def acuracia_proporcional(y_true, y_pred):
    proporcoes = []
    for true, pred in zip(y_true, y_pred):
        acertos_sent = 0
        for t, p in zip(true, pred):
            if t == p:
                acertos_sent += 1
        prop_sent = acertos_sent / len(true)
        proporcoes.append(prop_sent)

    return sum(proporcoes) / len(proporcoes)


def erros_mais_comuns_por_categoria(x, y_true, y_pred, categorias, n=20):
    errors = Counter()
    for feats, true, pred, cats in zip(x, y_true, y_pred, categorias):
        dif_tags = set()
        for i, (t, p) in enumerate(zip(true, pred)):
            if t != p:
                dif_tags.add((t, p))

        for dif in dif_tags:
            for c in cats:
                errors[(dif, c)] += 1

    return errors.most_common(n)


def show(sent: list[str], y_true: list[str], y_pred: list[str]):
    if len(sent) == 0:
        return

    max_len = max([len(t) for t in sent]) + 2
    print(f"{'String':<{max_len}} {'Target':<10} {'Predito':<10}")
    print("----------------------------------")
    for s, t, p in zip(sent, y_true, y_pred):
        print(f"{s:<{max_len}} {t:<10} {p:<10}")
    print("################################")


def avaliar(
    x: list[list[dict[str, float]]],
    y: list[list[str]],
    categorias: list[list[str]],
    tokens: list[list[str]],
):

    print("Executando modelo...")
    crf = sklearn_crfsuite.CRF(model_filename="./tagger.crf")

    y_pred = crf.predict(x)
    print(metrics.flat_classification_report(y, y_pred, zero_division=0.0))

    print(f"Acurácia no trecho completo: {metrics.sequence_accuracy_score(y, y_pred)}")

    print(f"Acurácia proporcional: {acuracia_proporcional(y, y_pred)}")

    print()

    pares_labels: dict[str, set[str]] = defaultdict(set)
    for y_i in y:
        for y_token in y_i:
            if "_" in y_token:
                pos_bio, tipo = y_token.split("_", 1)
                pares_labels[tipo].add(pos_bio)
            else:
                pares_labels[y_token] = set()

    labels = []
    for tipo, bios in pares_labels.items():
        if len(bios) == 0:
            labels.append((tipo,))
        else:
            labels.append(tuple(sorted(f"{bio}_{tipo}" for bio in bios)))

    for l in labels:
        acertos, n = acuracia_labels(y, y_pred, l)
        print(f"Acurácia de {l}: {acertos}/{n} = {acertos / n:.2}")

    print()

    print("Erros Token:")
    pprint(erros_mais_comuns_token(x, y, y_pred))

    print()
    print("Erros Features:")
    pprint(erros_mais_comuns_feature(x, y, y_pred))

    print()
    print("Erros Categorias:")
    pprint(erros_mais_comuns_por_categoria(x, y, y_pred, categorias))

    # print("Amostra erros:")
    # amostra = amostra_erros(tokens, y, y_pred, n=7)
    # for a in amostra:
    #     show(*a)

    print()
    for classes in labels:
        amostra = amostra_erros(tokens, y, y_pred, n=5, classes=list(classes))
        print(f"Amostra de Erros de {classes!s}")
        for a in amostra:
            show(*a)


def consulta_duckdb(query: str, batch_size: int = 1000):
    con = sqlite3.connect("./dataset.sqlite")
    consulta = con.execute(query)

    while batch := consulta.fetchmany(batch_size):
        for b in batch:
            yield b

    con.close()


def main():
    dados = consulta_duckdb("""select endereco, resposta_llm, origem, uf
from enderecos
where resposta_llm is not null 
  and (resposta_llm ->> '$.erro') is null;
""")

    extrator_features = ExtratorFeature()

    x: list[list[dict[str, float]]] = []
    y: list[list[str]] = []
    categorias: list[list[str]] = []
    tokens: list[list[str]] = []

    for endereco, resposta_str, origem, uf in dados:
        resposta = json.loads(resposta_str)
        segmentos = resposta.get("segmentos", [])
        toks, labels = mergear(endereco, segmentos, tokenize)
        features = extrator_features.tokens2features(toks)

        x.append(features)
        y.append(labels)
        categorias.append([origem, uf])
        tokens.append(toks)

    avaliar(x, y, categorias, tokens)


if __name__ == "__main__":
    main()
