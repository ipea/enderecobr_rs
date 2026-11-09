from crf_endereco.cli.explicar import (
    _concorrente,
    _estilo_peso,
    _estilo_tipo,
    _formatar,
    _texto_tag,
    campos_preferidos,
    estruturar_segmentos,
    features_com_pesos,
)


def test_features_com_pesos_ordena_e_marca_sem_peso():
    state_features = {
        ("bias", "B_LOGRADOURO"): 1.5,
        ("0:RUA", "B_LOGRADOURO"): 4.7,
        ("0:tam:3", "B_LOGRADOURO"): -2.1,
    }
    feats = {"bias": 1.0, "0:tam:3": 1.0, "0:RUA": 1.0, "0:is_alpha": 1.0}

    linha = features_com_pesos(feats, "B_LOGRADOURO", state_features)

    assert str(linha) == "0:RUA +4.7 0:tam:3 -2.1 bias +1.5 0:is_alpha — "


def test_estilo_peso_e_divergente_e_cresce_com_modulo():
    assert _estilo_peso(4.0) == "bold color(46)"
    assert _estilo_peso(2.0) == "color(40)"
    assert _estilo_peso(0.5) == "color(114)"
    assert _estilo_peso(-0.5) == "color(217)"
    assert _estilo_peso(-2.0) == "color(203)"
    assert _estilo_peso(-4.0) == "bold color(196)"


def test_concorrente_ignora_a_tag_vencedora():
    marginal = {"B_LOCALIDADE": 0.62, "B_PONTO_REFERENCIA": 0.31, "O": 0.07}

    assert _concorrente(marginal, "B_LOCALIDADE") == ("B_PONTO_REFERENCIA", 0.31)


def test_estilo_tipo_fixa_distinto_e_estavel_para_desconhecido():
    assert _estilo_tipo("complemento") != _estilo_tipo("recurso_natural")
    assert _estilo_tipo("desconhecido") == _estilo_tipo("desconhecido")


def test_texto_tag_estilo_b_io_e_o():
    assert str(_texto_tag("O").style) == "dim"
    assert "bold" in str(_texto_tag("B_LOGRADOURO").style)
    assert "bold" not in str(_texto_tag("I_LOGRADOURO").style)


def test_campos_preferidos_seguem_a_politica_do_rust():
    assert campos_preferidos("logradouro", None) == (["logradouro"], False)
    assert campos_preferidos("numero", "numero") == (["numero", "complemento"], False)
    assert campos_preferidos("parcela", "logradouro") == (["logradouro"], True)
    assert campos_preferidos("parcela", "numero") == (
        ["logradouro", "complemento"],
        True,
    )
    assert campos_preferidos("nucleo_rural", None) == (
        ["logradouro", "localidade"],
        False,
    )
    assert campos_preferidos("complemento", "numero") == (["complemento"], True)
    assert campos_preferidos("localidade", None) == (["localidade"], False)
    assert campos_preferidos("referencia", None) == ([], False)


def test_estruturar_segmentos_concatena_parcela_no_logradouro():
    segmentos = [
        {"tipo": "logradouro", "valor": "r x"},
        {"tipo": "numero", "valor": "123"},
        {"tipo": "parcela", "valor": "qd 5"},
        {"tipo": "logradouro", "valor": "r y"},
        {"tipo": "cep", "valor": "22000-000"},
    ]

    campos = estruturar_segmentos(segmentos)

    assert campos == {
        "logradouro": "r x qd 5",
        "numero": "123",
        "complemento": None,
        "localidade": None,
        "cep": "22000-000",
    }


def test_estruturar_segmentos_concatena_complementos():
    segmentos = [
        {"tipo": "logradouro", "valor": "r x"},
        {"tipo": "numero", "valor": "123"},
        {"tipo": "complemento", "valor": "apto 45"},
        {"tipo": "complemento", "valor": "bloco b"},
    ]

    assert estruturar_segmentos(segmentos)["complemento"] == "apto 45 bloco b"


def test_formatar_junta_os_campos_na_ordem_do_endereco():
    assert (
        _formatar(
            {
                "logradouro": "RUA X",
                "numero": None,
                "complemento": None,
                "localidade": "ASA NORTE",
                "cep": "22000-000",
            }
        )
        == "RUA X, ASA NORTE, 22000-000"
    )
