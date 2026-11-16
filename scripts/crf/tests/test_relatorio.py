from crf_endereco.modelo.relatorio import contagens_por_rotulo, medir


def test_medir_conta_endereco_perfeito_so_quando_todos_os_rotulos_batem():
    y = [["B_LOGRADOURO", "I_LOGRADOURO"], ["B_NUMERO", "O"]]
    previsto = [["B_LOGRADOURO", "I_LOGRADOURO"], ["B_NUMERO", "B_NUMERO"]]

    desempenho = medir(y, previsto)

    # tres dos quatro tokens certos, mas so um dos dois enderecos inteiro
    assert desempenho.token == 0.75
    assert (desempenho.perfeitos, desempenho.enderecos) == (1, 2)
    assert desempenho.fracao_perfeita == 0.5
    # media das fracoes: (1.0 + 0.5) / 2
    assert desempenho.proporcional == 0.75


def test_medir_sem_endereco_nao_divide_por_zero():
    desempenho = medir([], [])

    assert (desempenho.token, desempenho.perfeitos, desempenho.proporcional) == (
        0.0,
        0,
        0.0,
    )
    assert desempenho.fracao_perfeita == 0.0


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
