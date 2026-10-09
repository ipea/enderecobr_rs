import json
import sqlite3

import sklearn_crfsuite

from crf_endereco.preproc import (
    ExtratorFeature,
    tokenize,
)


mapa_tipo_segmento = {
    # "logradouro_interno": "logradouro",
    "modificador_numero": "numero",
    "cadastro": None,
    # "quilometragem_via": "logradouro",
    # "denominacao": None,
    # "empreendimento": None,
    # "parcela": None,
    "ruido": None,
    "outros": None,
    # "descricao_area": None,
}


def mergear(endereco: str, segmentos: list[dict[str, str]], tokenizer):
    toks_segmentos: list[tuple[str, str]] = []

    for segmento in segmentos:
        texto_segmento = segmento.get("valor", "")
        tipo_segmento = segmento.get("tipo", "")
        for i, tok in enumerate(tokenizer(texto_segmento)):
            if tipo_segmento in mapa_tipo_segmento:
                tipo_segmento = mapa_tipo_segmento[tipo_segmento]

            if tipo_segmento is None:
                toks_segmentos.append((tok, "O"))
            elif i == 0:
                toks_segmentos.append((tok, f"B_{tipo_segmento.upper()}"))
            else:
                toks_segmentos.append((tok, f"I_{tipo_segmento.upper()}"))

    toks_endereco = tokenizer(endereco)
    toks_labels: list[str] = []
    pos_segmento = 0

    for tok in toks_endereco:
        if pos_segmento < len(toks_segmentos):
            seg_atual = toks_segmentos[pos_segmento]
        else:
            seg_atual = None

        if seg_atual is not None and tok == seg_atual[0]:
            toks_labels.append(seg_atual[1])
            pos_segmento += 1
        else:
            toks_labels.append("O")

    assert len(toks_labels) == len(toks_endereco)
    return toks_endereco, toks_labels


def main():
    query = """select endereco, resposta_llm 
from enderecos
where resposta_llm is not null 
  and (resposta_llm ->> '$.erro') is null;
"""
    con = sqlite3.connect("./dataset.sqlite")
    print("Coletando dados...")
    dados = con.execute(query).fetchall()
    con.close()

    extrator_features = ExtratorFeature()

    x: list[list[dict[str, float]]] = []
    y: list[list[str]] = []

    print("Preprocessando dados...")
    for endereco, resposta_str in dados:
        resposta = json.loads(resposta_str)
        segmentos = resposta.get("segmentos", [])
        tokens, labels = mergear(endereco, segmentos, tokenize)
        features = extrator_features.tokens2features(tokens)

        x.append(features)
        y.append(labels)

    print(f"Realizando treinamento (n={len(x)})...")
    crf = sklearn_crfsuite.CRF(
        algorithm="lbfgs",
        # c1=0.01,
        verbose=True,
        c2=0.01,
        max_iterations=2000,
        all_possible_transitions=False,
        min_freq=2,
        model_filename="./tagger.crf",
    )
    _ = crf.fit(x, y)


if __name__ == "__main__":
    main()
