"""Treino do CRF sobre o dataset anotado."""

import json
import sqlite3
from pathlib import Path

from crf_endereco.config import CAMINHO_DATASET
from crf_endereco.features import ExtratorFeature, tokenize
from crf_endereco.rotulos import mergear


def carregar_dados(
    caminho: Path = CAMINHO_DATASET,
) -> tuple[list[list[dict[str, float]]], list[list[str]]]:
    """Lê o dataset etiquetado e devolve (features, rótulos) prontos para o CRF.

    Compartilhado entre `treinamento.py` e `tunning.py` para que os dois usem
    exatamente o mesmo caminho de dados e de etiquetagem.
    """
    try:
        con = sqlite3.connect(caminho)
        print("Coletando dados...")
        dados = con.execute("""select endereco, resposta_llm
from enderecos
where resposta_llm is not null
  and (resposta_llm ->> '$.erro') is null;
""").fetchall()
        con.close()
    except sqlite3.Error as erro:
        raise RuntimeError(f"Falha ao ler {caminho}: {erro}") from erro

    extrator_features = ExtratorFeature()

    x: list[list[dict[str, float]]] = []
    y: list[list[str]] = []

    print("Preprocessando dados...")
    for endereco, resposta_str in dados:
        try:
            resposta = json.loads(resposta_str)
        except json.JSONDecodeError as erro:
            raise RuntimeError(
                f"Resposta inválida no endereço {endereco!r}: {erro}"
            ) from erro
        segmentos = resposta.get("segmentos", [])
        tokens, labels = mergear(endereco, segmentos, tokenize)
        features = extrator_features.tokens2features(tokens)

        x.append(features)
        y.append(labels)

    return x, y
