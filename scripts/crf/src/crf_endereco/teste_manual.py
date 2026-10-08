import sklearn_crfsuite
from crf_endereco.preproc import ExtratorFeature, tokenize
from pprint import pprint


def extrair_campos(crf: sklearn_crfsuite.CRF, extrator: ExtratorFeature, frase: str):
    tokens = tokenize(frase)
    x = extrator.tokens2features(tokens)
    pred = crf.predict_single(x)

    return list(zip(tokens, pred))


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
        print(campos)


if __name__ == "__main__":
    main()
