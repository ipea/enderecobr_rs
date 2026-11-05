from crf_endereco.cli.explicar import (
    _concorrente,
    _estilo_peso,
    _estilo_tipo,
    _texto_tag,
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
