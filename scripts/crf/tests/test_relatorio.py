from crf_endereco.modelo.relatorio import (
    contagens_por_rotulo,
    medir,
    mesma_estrutura,
)


def test_medir_conta_endereco_perfeito_so_quando_todos_os_rotulos_batem():
    tokens = [["RUA", "A"], ["10", "AP"]]
    y = [["B_LOGRADOURO", "I_LOGRADOURO"], ["B_NUMERO", "O"]]
    previsto = [["B_LOGRADOURO", "I_LOGRADOURO"], ["B_NUMERO", "B_NUMERO"]]

    desempenho = medir(y, previsto, tokens)

    # tres dos quatro tokens certos, mas so um dos dois enderecos inteiro
    assert desempenho.token == 0.75
    assert (desempenho.perfeitos, desempenho.enderecos) == (1, 2)
    assert desempenho.fracao_perfeita == 0.5
    # media das fracoes: (1.0 + 0.5) / 2
    assert desempenho.proporcional == 0.75


def test_medir_sem_endereco_nao_divide_por_zero():
    desempenho = medir([], [], [])

    assert (desempenho.token, desempenho.perfeitos, desempenho.proporcional) == (
        0.0,
        0,
        0.0,
    )
    assert (desempenho.fracao_perfeita, desempenho.fracao_estrutura) == (0.0, 0.0)


def test_mesma_estrutura_ignora_abertura_nova_do_mesmo_tipo():
    tokens = ["RUA", "DAS", "FLORES"]
    y = ["B_LOGRADOURO", "I_LOGRADOURO", "I_LOGRADOURO"]
    previsto = ["B_LOGRADOURO", "I_LOGRADOURO", "B_LOGRADOURO"]

    assert mesma_estrutura(tokens, y, previsto)


def test_mesma_estrutura_ignora_pontuacao_de_corte_largada_em_o():
    # `RUA A, 123`: a virgula cai em O e abre um trecho novo do mesmo tipo.
    tokens = ["RUA", "A", ",", "123"]
    y = ["B_LOGRADOURO", "I_LOGRADOURO", "O", "B_NUMERO"]
    previsto = ["B_LOGRADOURO", "B_LOGRADOURO", "O", "B_NUMERO"]

    assert mesma_estrutura(tokens, y, previsto)


def test_mesma_estrutura_nao_perdoa_palavra_largada_em_o():
    # A palavra sai do campo e encurta o texto: e erro, nao ruido de fronteira.
    tokens = ["RUA", "DAS", "FLORES"]
    y = ["B_LOGRADOURO", "I_LOGRADOURO", "I_LOGRADOURO"]
    previsto = ["B_LOGRADOURO", "O", "I_LOGRADOURO"]

    assert not mesma_estrutura(tokens, y, previsto)


def test_mesma_estrutura_nao_perdoa_tipo_trocado():
    tokens = ["RUA", "123"]
    y = ["B_LOGRADOURO", "B_NUMERO"]
    previsto = ["B_LOGRADOURO", "B_LOGRADOURO"]

    assert not mesma_estrutura(tokens, y, previsto)


def test_medir_conta_endereco_perfeito_por_trecho():
    tokens = [["RUA", "DAS", "FLORES"], ["10", "AP"]]
    y = [
        ["B_LOGRADOURO", "I_LOGRADOURO", "I_LOGRADOURO"],
        ["B_NUMERO", "O"],
    ]
    previsto = [
        ["B_LOGRADOURO", "B_LOGRADOURO", "B_LOGRADOURO"],
        ["B_NUMERO", "O"],
    ]

    desempenho = medir(y, previsto, tokens)

    # o primeiro erra o rotulo (B onde era I) mas acerta o trecho
    assert desempenho.perfeitos == 1
    assert desempenho.estrutura == 2
    assert desempenho.so_fronteira == 1


def test_contagens_por_rotulo_separa_falso_positivo_de_falso_negativo():
    y = [["B_NUMERO", "O", "B_NUMERO"]]
    previsto = [["B_NUMERO", "B_NUMERO", "O"]]

    contagens = {linha[0]: linha[1:] for linha in contagens_por_rotulo(y, previsto)}

    # B_NUMERO: um acerto, um previsto a mais (fp) e um perdido (fn)
    assert contagens["B_NUMERO"] == (1, 1, 1)
    # O: um previsto que devia ser numero (fn) e um numero que virou O (fp)
    assert contagens["O"] == (0, 1, 1)


def test_contagens_por_rotulo_ordena_pelo_rotulo_que_mais_erra():
    y = [["O", "O", "O"], ["B_UF"]]
    previsto = [["B_NUMERO", "B_NUMERO", "B_NUMERO"], ["B_NUMERO"]]

    rotulos = [linha[0] for linha in contagens_por_rotulo(y, previsto)]

    # B_NUMERO erra 4 (todos previstos a mais), O erra 3 (todos perdidos)
    assert rotulos == ["B_NUMERO", "O", "B_UF"]
