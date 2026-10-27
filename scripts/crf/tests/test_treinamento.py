from crf_endereco.features import tokenize
from crf_endereco.rotulos import mergear


def test_mergear_alinha_tokens_e_rotulos():
    # Os segmentos vêm verbatim do texto, então o casing tem que bater.
    segmentos = [
        {"valor": "Rua das Flores", "tipo": "logradouro"},
        {"valor": "123", "tipo": "numero"},
        {"valor": "Apto 5", "tipo": "complemento"},
    ]
    tokens, labels = mergear("Rua das Flores, 123, Apto 5", segmentos, tokenize)

    assert len(tokens) == len(labels)
    assert labels == [
        "B_LOGRADOURO",
        "I_LOGRADOURO",
        "I_LOGRADOURO",
        "O",  # vírgula separadora
        "B_NUMERO",
        "O",  # vírgula separadora
        "B_COMPLEMENTO",
        "I_COMPLEMENTO",
    ]


def test_mergear_marca_tipos_mapeados_como_ruido():
    segmentos = [
        {"valor": "Rua das Flores", "tipo": "logradouro"},
        {"valor": "Zona Rural", "tipo": "ruido"},
    ]
    _, labels = mergear("Rua das Flores Zona Rural", segmentos, tokenize)

    assert labels == ["B_LOGRADOURO", "I_LOGRADOURO", "I_LOGRADOURO", "O", "O"]


def test_mergear_endereco_sem_segmento_fica_todo_em_o():
    _, labels = mergear("Rua das Flores 123", [], tokenize)

    assert labels == ["O", "O", "O", "O"]
