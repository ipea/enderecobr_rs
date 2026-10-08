import sklearn_crfsuite
from crf_endereco.preproc import ExtratorFeature, tokenize
from pprint import pprint


def extrair_campos(crf: sklearn_crfsuite.CRF, extrator: ExtratorFeature, frase: str):
    tokens = tokenize(frase)
    x = extrator.tokens2features(tokens)
    pred = crf.predict_single(x)

    return list(zip(tokens, pred))


def coletar_segmentos(tokens_classificados: list[tuple[str, str]]):
    segmentos: list[dict[str, str]] = []
    ultimo_segmento = None
    for tok, tok_tipo in tokens_classificados:
        if tok_tipo == "O":
            continue

        bos, tipo = tok_tipo.split("_", 1)
        tipo = tipo.lower()

        if bos == "B":
            ultimo_segmento = {"tipo": tipo, "valor": tok}
            segmentos.append(ultimo_segmento)
        if bos == "I":
            if ultimo_segmento is not None and ultimo_segmento["tipo"] == tipo:
                ultimo_segmento["valor"] += " " + tok
    return segmentos


def main():
    # Por algum motivo, basta só importar isso para a função
    # input funcionar adequadamente.
    import readline as _

    crf = sklearn_crfsuite.CRF(model_filename="./tagger.crf")
    extrator = ExtratorFeature()

    while True:
        try:
            line = input()
        except EOFError:
            break
        if not line:
            continue
        campos = extrair_campos(crf, extrator, line)
        pprint(coletar_segmentos(campos))


if __name__ == "__main__":
    main()
