import pytest

import enderecobr

# Testes bem simples só para garantir que as funções estão sendo executadas.


def testa_logradouro():
    assert enderecobr.padronizar_logradouros("R") == "RUA"


def testa_numero():
    assert enderecobr.padronizar_numeros("0001") == "1"


def testa_padronizar_complementos():
    assert enderecobr.padronizar_complementos("ap 101") == "APARTAMENTO 101"


def testa_bairro():
    assert enderecobr.padronizar_bairros("NS aparecida") == "NOSSA SENHORA APARECIDA"


def testa_municipio():
    assert enderecobr.padronizar_municipios("3304557") == "RIO DE JANEIRO"


def testa_estado_nome():
    assert enderecobr.padronizar_estados_para_nome("MA") == "MARANHAO"


def testa_padronizar_tipo_logradouro():
    assert enderecobr.padronizar_tipo_logradouro("R") == "RUA"


def testa_padronizar_cep_leniente():
    assert enderecobr.padronizar_cep_leniente("a123b45  6") == "00123-456"


def testa_padronizar_adhoc():
    pad = enderecobr.Padronizador()
    pad.adicionar_substituicoes([[r"R\.", "RUA"]])
    assert pad.padronizar("R. AZUL") == "RUA AZUL"
    assert pad.obter_substituicoes() == [(r"R\.", "RUA", None)]


def testa_metaphone():
    assert enderecobr.metaphone("casa") == "KASA"


def testa_padronizar_numeros_por_extenso():
    assert enderecobr.padronizar_numeros_por_extenso("CASA 1") == "CASA UM"


def testa_padronizar_numero_romano_por_extenso():
    assert (
        enderecobr.padronizar_numero_romano_por_extenso("PAPA PIO II")
        == "PAPA PIO DOIS"
    )


def testa_numero_por_extenso():
    assert enderecobr.numero_por_extenso(20) == "VINTE"


def testa_romano_para_inteiro():
    assert enderecobr.romano_para_inteiro("VI") == 6


def testa_padronizar_estados_para_codigo():
    assert enderecobr.padronizar_estados_para_codigo("MA") == "21"


def testa_padronizar_estados_para_sigla():
    assert enderecobr.padronizar_estados_para_sigla("21") == "MA"


def testa_padronizar_numeros_para_int():
    assert enderecobr.padronizar_numeros_para_int("0210") == 210
    assert enderecobr.padronizar_numeros_para_int("S/N") is None


def testa_padronizar_numeros_para_string():
    assert enderecobr.padronizar_numeros_para_string(210) == "210"
    assert enderecobr.padronizar_numeros_para_string(0) == "S/N"


def testa_identificar_dado_faltante():
    assert enderecobr.is_dado_faltante("SI") is True
    assert enderecobr.is_dado_faltante("RUA") is False


def testa_normalizar():
    assert enderecobr.normalizar("Olá, mundo") == "OLA, MUNDO"


def testa_padronizar_cep():
    assert enderecobr.padronizar_cep("12345-6") == "00123-456"


def testa_padronizar_cep_numerico():
    assert enderecobr.padronizar_cep_numerico(123456) == "00123-456"


def testa_identificador_padroes():
    idp = enderecobr.IdentificadorPadroes()
    idp.adicionar(["RUA", "AVENIDA"])
    assert idp.identificar("RUA AZUL") is True
    assert idp.identificar("TRAVESSA") is False


def testa_padronizador_adicionar():
    pad = enderecobr.Padronizador()
    pad.adicionar(r"R\.", "RUA")
    pad.preparar()
    assert pad.padronizar("R. AZUL") == "RUA AZUL"


def testa_padronizador_adicionar_com_ignorar():
    pad = enderecobr.Padronizador()
    pad.adicionar_com_ignorar(r"^R ", "RUA ", r"R APT")
    pad.preparar()
    assert pad.padronizar("R APT AMARELA") == "R APT AMARELA"
    assert pad.padronizar("R AMARELA") == "RUA AMARELA"


def testa_padronizador_adicionar_vetores():
    pad = enderecobr.Padronizador()
    pad.adicionar_vetores(["R ", "AV "], ["RUA ", "AVENIDA "], [None, None])
    assert pad.padronizar("R AZUL") == "RUA AZUL"


def testa_padronizador_obter_vetores():
    pad = enderecobr.Padronizador()
    pad.adicionar_substituicoes([["R ", "RUA "]])
    assert pad.obter_vetores() == (["R "], ["RUA "], [None])


def testa_separador_sem_modelo():
    separador = enderecobr.SeparadorEndereco()

    with pytest.raises(RuntimeError, match="Nenhum modelo carregado"):
        _ = separador.segmentar("av n sra copacabana, 123")

    # Testa também usando o método estático.
    with pytest.raises(RuntimeError, match="Não foi possível carregar o modelo"):
        _ = enderecobr.SeparadorEndereco.carregar("/nao/existe/tagger.crf")


def testa_endereco_construtor_e_padronizar():
    endereco = enderecobr.Endereco(logradouro="r. gen glicerio", numero="001")
    assert endereco.complemento is None

    endereco.complemento = "apt 405"
    endereco.padronizar()

    assert endereco.logradouro == "RUA GENERAL GLICERIO"
    assert endereco.numero == "1"
    assert endereco.complemento == "APARTAMENTO 405"
    assert endereco.formatar() == "RUA GENERAL GLICERIO, 1, APARTAMENTO 405"


def testa_endereco_copia_padronizada():
    endereco = enderecobr.Endereco(logradouro="r. do aco", cep="20040020")
    padronizado = endereco.endereco_padronizado()

    assert padronizado.logradouro == "RUA DO ACO"
    assert padronizado.cep == "20040-020"
    assert endereco.logradouro == "r. do aco"


def testa_endereco_repr():
    endereco = enderecobr.Endereco(logradouro="RUA A", numero="1")
    assert (
        repr(endereco)
        == 'Endereco(logradouro="RUA A", numero="1", complemento=None, localidade=None, cep=None)'
    )
