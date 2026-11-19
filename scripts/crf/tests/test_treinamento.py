import random

import pytest
import typer

from crf_endereco.features import tokenize
from crf_endereco.modelo.crf import (
    Exemplos,
    _numeros_trocados,
    _sem_cabeca,
    _sem_pontuacao,
    alvo_vazio,
    validacao_cruzada,
)
from crf_endereco.modelo.relatorio import matriz_confusao
from crf_endereco.rotulos import alinhamento, mergear


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


def test_alinhamento_devolve_o_segmento_que_nao_casa_com_token():
    # Palavra colada na base de origem: "CARAMURU" existe no texto mas não é
    # token, então o ponteiro trava e o resto do endereço ficaria todo em `O`.
    segmentos = [
        {"valor": "Rua A", "tipo": "logradouro"},
        {"valor": "Caramuru", "tipo": "empreendimento"},
        {"valor": "Rua B", "tipo": "logradouro"},
    ]
    tokens, labels, residuo = alinhamento(
        "Rua A CaramuruAntiga Rua B", segmentos, tokenize
    )

    assert tokens == ["Rua", "A", "CaramuruAntiga", "Rua", "B"]
    assert labels == ["B_LOGRADOURO", "I_LOGRADOURO", "O", "O", "O"]
    assert residuo == ["Caramuru", "Rua", "B"]


def test_alinhamento_nao_devolve_residuo_quando_tudo_casa():
    segmentos = [{"valor": "Rua A", "tipo": "logradouro"}]

    _, _, residuo = alinhamento("Rua A 123", segmentos, tokenize)

    assert residuo == []


def test_alinhamento_tira_a_pontuacao_que_abre_o_segmento():
    # `, 123` como número poria `B_NUMERO` na vírgula, que em todo o resto do
    # corpus é `O`: a vírgula é o corte, não o começo do campo.
    segmentos = [
        {"valor": "Rua das Flores", "tipo": "logradouro"},
        {"valor": ", 123", "tipo": "numero"},
    ]
    _, labels, residuo = alinhamento("Rua das Flores, 123", segmentos, tokenize)

    assert labels == ["B_LOGRADOURO", "I_LOGRADOURO", "I_LOGRADOURO", "O", "B_NUMERO"]
    assert residuo == []


def test_alinhamento_mantem_a_pontuacao_no_fim_do_segmento():
    # `AP.` e `C/`: a pontuação final pode ser da abreviação ou do marcador.
    segmentos = [{"valor": "AP. 1002 C/", "tipo": "complemento"}]
    _, labels, _ = alinhamento("AP. 1002 C/", segmentos, tokenize)

    assert labels[-1] == "I_COMPLEMENTO"


def test_matriz_confusao_conta_pares_em_ordem_alfabetica():
    rotulos, matriz = matriz_confusao(
        [["B_LOGRADOURO", "O", "B_NUMERO"]],
        [["B_LOGRADOURO", "O", "O"]],
    )

    assert rotulos == ["B_LOGRADOURO", "B_NUMERO", "O"]
    assert matriz == [[1, 0, 0], [0, 0, 1], [0, 0, 1]]


def test_matriz_confusao_inclui_rotulo_so_previsto():
    rotulos, matriz = matriz_confusao([["O"]], [["B_CEP"]])

    assert rotulos == ["B_CEP", "O"]
    assert matriz == [[0, 0], [1, 0]]


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


def test_sem_cabeca_tira_o_codigo_o_que_abre_o_endereco():
    # `Q SQN 404 BLOCO G 101`: o Q e codigo da base, nao parte do endereco.
    toks = ["Q", "SQN", "404", "BLOCO", "G", "101"]
    labels = ["O", "B_LOGRADOURO", "I_LOGRADOURO", "I_LOGRADOURO", "I_LOGRADOURO", "B_NUMERO"]

    assert _sem_cabeca(toks, labels) == (toks[1:], labels[1:])


def test_sem_cabeca_nao_gera_variante_sem_codigo_inicial():
    toks = ["RUA", "A", "10"]
    labels = ["B_LOGRADOURO", "I_LOGRADOURO", "B_NUMERO"]

    assert _sem_cabeca(toks, labels) is None
    # endereco inteiro em `O` nao tem cabeca a tirar, so alvo vazio
    assert _sem_cabeca(["X"], ["O"]) is None


def test_numeros_trocados_mantem_tamanho_e_separadores():
    toks = ["AV", "BRASIL", "69049-992", "KM", "2,5"]
    labels = [
        "B_LOGRADOURO",
        "I_LOGRADOURO",
        "B_CEP",
        "B_QUILOMETRAGEM_VIA",
        "I_QUILOMETRAGEM_VIA",
    ]

    trocados, labels_novos = _numeros_trocados(toks, labels, random.Random(1)) or ([], [])

    assert labels_novos == labels
    # so os digitos mudam: forma de cada token (tamanho, hifen, virgula) fica
    for novo, original in zip(trocados, toks, strict=True):
        assert len(novo) == len(original)
        assert [c.isdigit() for c in novo] == [c.isdigit() for c in original]
    assert trocados[:2] == ["AV", "BRASIL"]


def test_numeros_trocados_sem_digito_nao_gera_variante():
    sem_numero = _numeros_trocados(
        ["RUA", "A"], ["B_LOGRADOURO", "I_LOGRADOURO"], random.Random(1)
    )

    assert sem_numero is None


def test_alvo_vazio_pega_endereco_sem_rotulo_aprendivel():
    assert alvo_vazio(["O", "O", "O"])
    assert not alvo_vazio(["O", "B_NUMERO"])
    # lista vazia nao e um endereco: quem chama ja filtrou
    assert alvo_vazio([])


def test_validacao_cruzada_preve_todo_exemplo_fora_do_fold():
    # Tres enderecos distintos, um por rotulo: o fold que preve cada um nao o
    # treinou, entao o unico acerto possivel e o padrao repetido.
    enderecos = [
        ["RUA", "A"],
        ["RUA", "B"],
        ["RUA", "C"],
        ["RUA", "D"],
        ["RUA", "E"],
        ["RUA", "F"],
    ]
    rotulos = [
        ["B_LOGRADOURO", "I_LOGRADOURO"],
        ["B_LOGRADOURO", "I_LOGRADOURO"],
        ["B_LOGRADOURO", "I_LOGRADOURO"],
        ["B_LOGRADOURO", "I_LOGRADOURO"],
        ["B_LOGRADOURO", "I_LOGRADOURO"],
        ["B_LOGRADOURO", "I_LOGRADOURO"],
    ]
    exemplos = Exemplos(
        x=[[{"0:RUA": 1.0}, {"bias": 1.0}] for _ in enderecos],
        y=rotulos,
        tokens=enderecos,
        categorias=[["origem", "uf"] for _ in enderecos],
        hashes=[f"h{i}" for i in range(len(enderecos))],
    )

    previsto = validacao_cruzada(exemplos, folds=3, estratificar_por="nenhum")

    assert len(previsto) == len(exemplos.y)
    assert all(len(linha) == 2 for linha in previsto)


def test_validacao_cruzada_recusa_menos_de_dois_folds():
    exemplos = Exemplos(x=[], y=[], tokens=[], categorias=[], hashes=[])

    with pytest.raises(typer.BadParameter):
        validacao_cruzada(exemplos, folds=1)
