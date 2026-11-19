"""Mede o efeito de `aumentar` na regua de validacao cruzada, por rotulo.

Os dois bracos (sem e com aumento) sao previstos fora do fold e as previsoes
ficam em `data/saidas/aumento/`, para analise posterior nao custar outro treino.
"""

from __future__ import annotations

import json
import re
import time
from collections import Counter
from pathlib import Path
from typing import Any

from crf_endereco.modelo.crf import (
    SEMENTE_SPLIT,
    Exemplos,
    _indices_folds,
    _novo_crf,
    _recortar,
    aumentar,
    carregar_exemplos,
)

FOLDS = 3
PASTA = Path("data/saidas/aumento")
LITERAL = re.compile(r"[\d.,/-]+")


def _e_literal(attr: str) -> bool:
    """Feature cujo atributo e um valor numerico (`0:404`), nao uma forma (`0:tam:3`)."""
    _, _, valor = attr.partition(":")
    return bool(valor) and bool(LITERAL.fullmatch(valor))


def prever(
    exemplos: Exemplos, com_aumento: bool
) -> tuple[list[list[str]], dict[str, float]]:
    """Rotulos fora do fold, mais o retrato do primeiro modelo de cada braco."""
    previsto: list[list[str]] = [[] for _ in exemplos.y]
    retrato: dict[str, float] = {}
    for numero, (treino, teste) in enumerate(
        _indices_folds(exemplos, FOLDS, SEMENTE_SPLIT, "origem"), start=1
    ):
        conjunto = _recortar(exemplos, treino)
        if com_aumento:
            conjunto = aumentar(conjunto)
        crf = _novo_crf(verboso=False)
        crf.fit(conjunto.x, conjunto.y)
        if numero == 1:
            features = crf.state_features_ or {}
            retrato = {
                "treino": len(conjunto.y),
                "features": len(features),
                "literais": sum(1 for attr, _ in features if _e_literal(attr)),
                "mb": round((crf.size_ or 0) / 1_000_000, 2),
            }
        tags = crf.predict([exemplos.x[i] for i in teste])
        for i, previsao in zip(teste, tags, strict=True):
            previsto[i] = [str(tag) for tag in previsao]
        print(f"  fold {numero}/{FOLDS}: treino {len(conjunto.y)}", flush=True)
    return previsto, retrato


def resumo(
    exemplos: Exemplos, previsto: list[list[str]], indices: list[int]
) -> dict[str, float]:
    exatos = tokens = tokens_ok = 0
    for i in indices:
        gold, pred = exemplos.y[i], previsto[i]
        if not pred:
            continue
        exatos += int(list(pred) == list(gold))
        tokens += len(gold)
        tokens_ok += sum(1 for a, b in zip(gold, pred, strict=True) if a == b)
    return {
        "n": len(indices),
        "endereco": 100 * exatos / len(indices),
        "token": 100 * tokens_ok / tokens,
    }


def por_rotulo(
    exemplos: Exemplos, previsto: list[list[str]]
) -> dict[str, dict[str, float]]:
    """Precisao e recall por rotulo (acerto global nao separa poluicao de omissao)."""
    tp: Counter[str] = Counter()
    fp: Counter[str] = Counter()
    fn: Counter[str] = Counter()
    for gold, pred in zip(exemplos.y, previsto, strict=True):
        if not pred:
            continue
        for real, visto in zip(gold, pred, strict=True):
            if real == visto:
                tp[real] += 1
            else:
                fp[visto] += 1
                fn[real] += 1
    medidas: dict[str, dict[str, float]] = {}
    for rotulo in sorted(set(tp) | set(fn)):
        suporte = tp[rotulo] + fn[rotulo]
        if suporte < 100:
            continue
        medidas[rotulo] = {
            "suporte": suporte,
            "precisao": 100 * tp[rotulo] / (tp[rotulo] + fp[rotulo]),
            "recall": 100 * tp[rotulo] / suporte,
        }
    return medidas


def main() -> None:
    exemplos = carregar_exemplos()
    todos = [i for i in range(len(exemplos.y)) if exemplos.y[i]]
    df = [i for i in todos if exemplos.categorias[i][1] == "DF"]
    cabeca = [i for i in todos if exemplos.y[i][0] == "O"]
    PASTA.mkdir(parents=True, exist_ok=True)

    bracos: dict[str, dict[str, Any]] = {}
    for nome, com_aumento in (("sem", False), ("com", True)):
        print(f"\n=== {nome} aumento ===", flush=True)
        inicio = time.time()
        previsto, retrato = prever(exemplos, com_aumento)
        recortes = {
            "todos": resumo(exemplos, previsto, todos),
            "DF": resumo(exemplos, previsto, df),
            "cabeca": resumo(exemplos, previsto, cabeca),
        }
        bracos[nome] = {
            "retrato": retrato,
            "resumo": recortes,
            "rotulos": por_rotulo(exemplos, previsto),
            "segundos": round(time.time() - inicio),
        }
        _ = (PASTA / f"previsto_{nome}.json").write_text(json.dumps(previsto))
        _ = (PASTA / f"metricas_{nome}.json").write_text(
            json.dumps(bracos[nome], indent=1, ensure_ascii=False)
        )
        print(f"  {recortes}", flush=True)

    print("\n=== rotulos (suporte >= 100) ===", flush=True)
    print(f"{'rotulo':22s} {'prec sem':>9s} {'prec com':>9s} {'d':>6s} "
          f"{'rec sem':>8s} {'rec com':>8s} {'d':>6s}", flush=True)
    for rotulo, sem in bracos["sem"]["rotulos"].items():
        com = bracos["com"]["rotulos"].get(rotulo, sem)
        print(
            f"{rotulo:22s} {sem['precisao']:9.1f} {com['precisao']:9.1f} "
            f"{com['precisao'] - sem['precisao']:6.1f} {sem['recall']:8.1f} "
            f"{com['recall']:8.1f} {com['recall'] - sem['recall']:6.1f}",
            flush=True,
        )
    print("\nretrato (fold 1):", flush=True)
    print(json.dumps({n: b["retrato"] for n, b in bracos.items()}), flush=True)


if __name__ == "__main__":
    main()
