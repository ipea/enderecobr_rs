from crf_endereco.rotulos import (
    CONCORDA_COM_O_CRF,
    ROTULO_MANTIDO,
    ROTULO_NOVO,
    Mudanca,
    comparar,
)


def test_comparar_marca_so_o_token_em_que_as_tres_etiquetas_diferem():
    mudancas, veredito = comparar(
        ["RUA", "X"],
        ["B_LOGRADOURO", "B_LOCALIDADE"],
        ["B_LOGRADOURO", "I_LOGRADOURO"],
        ["B_LOGRADOURO", "O"],
    )

    assert mudancas == [Mudanca("X", "B_LOCALIDADE", "I_LOGRADOURO", "O")]
    assert veredito == ROTULO_NOVO


def test_comparar_ve_quando_a_llm_passa_a_concordar_com_o_crf():
    mudancas, veredito = comparar(
        ["X"], ["B_LOCALIDADE"], ["B_LOGRADOURO"], ["B_LOGRADOURO"]
    )

    assert mudancas == [Mudanca("X", "B_LOCALIDADE", "B_LOGRADOURO", "B_LOGRADOURO")]
    assert veredito == CONCORDA_COM_O_CRF


def test_comparar_ve_quando_a_llm_mantem_o_rotulo():
    mudancas, veredito = comparar(["X"], ["B_LOCALIDADE"], ["O"], ["B_LOCALIDADE"])

    assert mudancas == [Mudanca("X", "B_LOCALIDADE", "O", "B_LOCALIDADE")]
    assert veredito == ROTULO_MANTIDO


def test_comparar_sem_divergencia_nao_muda_nada():
    mudancas, veredito = comparar(["X"], ["O"], ["O"], ["O"])

    assert mudancas == []
    assert veredito == CONCORDA_COM_O_CRF
