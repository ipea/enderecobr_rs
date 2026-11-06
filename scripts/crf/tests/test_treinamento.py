from crf_endereco.features import tokenize
from crf_endereco.modelo.crf import _sem_pontuacao
from crf_endereco.modelo.relatorio import matriz_confusao
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


def test_matriz_confusao_conta_pares_e_coloca_o_primeiro():
    rotulos, matriz = matriz_confusao(
        [["B_LOGRADOURO", "O", "B_NUMERO"]],
        [["B_LOGRADOURO", "O", "O"]],
    )

    assert rotulos == ["O", "B_LOGRADOURO", "B_NUMERO"]
    assert matriz == [[1, 0, 0], [0, 1, 0], [1, 0, 0]]


def test_matriz_confusao_inclui_rotulo_so_previsto():
    rotulos, matriz = matriz_confusao([["O"]], [["B_CEP"]])

    assert rotulos == ["O", "B_CEP"]
    assert matriz == [[0, 1], [0, 0]]


def test_sem_pontuacao_remove_pontuacao_entre_trechos_de_tipos_diferentes():
    toks = ["RUA", "A", ",", "123"]
    labels = ["B_LOGRADOURO", "I_LOGRADOURO", "O", "B_NUMERO"]

    assert _sem_pontuacao(toks, labels) == (
        ["RUA", "A", "123"],
        ["B_LOGRADOURO", "I_LOGRADOURO", "B_NUMERO"],
    )


def test_sem_pontuacao_preserva_virgula_entre_trechos_do_mesmo_tipo():
    # "GLEBA 1, LOTE 2": sem a virgula a emenda entre as duas parcelas fica ambigua.
    toks = ["GLEBA", "1", ",", "LOTE", "2"]
    labels = ["B_PARCELA", "I_PARCELA", "O", "B_PARCELA", "I_PARCELA"]

    assert _sem_pontuacao(toks, labels) is None


def test_sem_pontuacao_remove_pontuacao_de_dentro_do_trecho():
    toks = ["S", "/", "N"]
    labels = ["B_NUMERO", "I_NUMERO", "I_NUMERO"]

    assert _sem_pontuacao(toks, labels) == (["S", "N"], ["B_NUMERO", "I_NUMERO"])


def test_sem_pontuacao_nao_gera_variante_sem_pontuacao_dispensavel():
    toks = ["RUA", "A"]
    labels = ["B_LOGRADOURO", "I_LOGRADOURO"]

    assert _sem_pontuacao(toks, labels) is None
