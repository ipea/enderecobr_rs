import json
import sqlite3

import sklearn_crfsuite
import sklearn_crfsuite.metrics
from sklearn.model_selection import train_test_split

from crf_endereco.preproc import (
    ExtratorFeature,
    tokenize,
)

mapa_tipo_segmento = {
    # "logradouro_interno": "logradouro",
    # "modificador_numero": None,
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


CAMINHO_DATASET = "./dataset.sqlite"


def carregar_dados(
    caminho: str = CAMINHO_DATASET,
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


def main():
    x, y = carregar_dados()
    (
        x_train,
        x_test,
        y_train,
        y_test,
    ) = train_test_split(x, y, test_size=0.1, random_state=42)

    print(f"Realizando treinamento (n={len(x_train)})...")
    crf = sklearn_crfsuite.CRF(
        algorithm="lbfgs",
        # c1=0.01,
        verbose=True,
        c2=0.01,
        max_iterations=5_000,
        all_possible_transitions=False,
        min_freq=2,
        model_filename="./tagger.crf",
    )
    modelo = crf.fit(x_train, y_train)
    y_pred = modelo.predict(x_test)

    flat_acc = sklearn_crfsuite.metrics.flat_accuracy_score(
        y_true=y_test, y_pred=y_pred
    )
    print(f"Acurácia: {flat_acc:.2f}")
    print(
        sklearn_crfsuite.metrics.flat_classification_report(
            y_test, y_pred, zero_division=0.0
        )
    )


if __name__ == "__main__":
    main()
