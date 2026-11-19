"""Compara taggers nos exemplos que sao teste de TODOS eles.

O split muda quando o dataset muda: um endereco que e teste do modelo novo pode
ter sido treino do antigo, e ai o antigo "acerta" por memorizacao (v15 marca
96% no recorte do v16, porque viu quase tudo). Medir na interseccao dos testes
garante que nenhum dos modelos viu o exemplo.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import sklearn_crfsuite

from crf_endereco.config import CAMINHO_DATASET
from crf_endereco.dataset import abrir_banco, ler_recorte
from crf_endereco.modelo.crf import Exemplos, carregar_exemplos, nome_do_modelo
from crf_endereco.modelo.relatorio import medir


def _recortar(exemplos: Exemplos, hashes: set[str]) -> Exemplos:
    indices = [i for i, hash_ in enumerate(exemplos.hashes) if hash_ in hashes]
    return Exemplos(
        x=[exemplos.x[i] for i in indices],
        y=[exemplos.y[i] for i in indices],
        tokens=[exemplos.tokens[i] for i in indices],
        categorias=[exemplos.categorias[i] for i in indices],
        hashes=[exemplos.hashes[i] for i in indices],
    )


def testes_comuns(caminhos: list[Path]) -> Exemplos:
    """Exemplos que estao no recorte de teste de todos os modelos."""
    exemplos = carregar_exemplos(CAMINHO_DATASET)
    conn = abrir_banco(CAMINHO_DATASET)
    try:
        testes = [
            ler_recorte(conn, nome_do_modelo(caminho))["teste"] for caminho in caminhos
        ]
    finally:
        conn.close()
    comuns = set.intersection(*testes)
    if not comuns:
        raise SystemExit("os modelos nao tem enderecos de teste em comum")
    return _recortar(exemplos, comuns)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    _ = parser.add_argument(
        "--modelo", type=Path, nargs="+", required=True, help="taggers a comparar"
    )
    argumentos = parser.parse_args()
    caminhos: list[Path] = argumentos.modelo

    teste = testes_comuns(caminhos)
    print(f"teste comum aos {len(caminhos)} modelos: {len(teste.y)} enderecos\n")
    print(f"{'modelo':22s} {'token':>8s} {'exato':>8s} {'por trecho':>11s}")
    for caminho in caminhos:
        crf = sklearn_crfsuite.CRF(model_filename=str(caminho))
        previsto = [[str(tag) for tag in linha] for linha in crf.predict(teste.x)]
        d = medir(teste.y, previsto, teste.tokens)
        print(
            f"{caminho.name:22s} {100 * d.token:7.2f}% {100 * d.fracao_perfeita:7.2f}%"
            f" {100 * d.fracao_estrutura:10.2f}%"
        )


if __name__ == "__main__":
    main()
