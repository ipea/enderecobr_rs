import random

import pytest

from crf_endereco.anotacao.populacao import (
    FONTE_CADUNICO,
    FONTES,
    formatar_cep,
    montar_endereco_cadunico,
    normalizar_localidade,
    normalizar_numero,
)


@pytest.mark.parametrize(
    "localidade,unidade,esperado",
    [
        # UT estende o bairro com submidade (favela/complexo/conjunto): usa o UT.
        ("MARE", "MARE NOVA HOLANDA", "MARE NOVA HOLANDA"),
        (
            "PENHA",
            "PENHA VILA PROLETARIA DA PENHA",
            "PENHA VILA PROLETARIA DA PENHA",
        ),
        (
            "COMPLEXO DO ALEMAO",
            "COMPLEXO DO ALEMAO NOVA BRASILIA",
            "COMPLEXO DO ALEMAO NOVA BRASILIA",
        ),
        # Sufixo de ruído: cai para o bairro puro.
        ("MARE", "MARE OUTROS", "MARE"),
        ("MARE", "MARE AREA NORMAL", "MARE"),
        ("ROCINHA", "ROCINHA ROCINHA", "ROCINHA"),
        # UT é CRAS/município/unidade administrativa (não é localidade): ignora.
        ("GUANABARA", "CRAS IV PEDRO DE VIGO JUSSARA", "GUANABARA"),
        ("CENTRO", "SEDE DO MUNICIPIO", "CENTRO"),
        ("GAVEA", "ROCINHA ROCINHA", "GAVEA"),
        # UT sem o bairro como prefixo e sem bairro de reserva.
        (None, "ZONA RURAL", "ZONA RURAL"),
        ("", "ALAGOINHAS", "ALAGOINHAS"),
        # Sem UT (ou igual ao bairro): usa o bairro.
        ("CENTRO", None, "CENTRO"),
        ("CENTRO", "CENTRO", "CENTRO"),
        # Normaliza caixa/espaços.
        ("  mare ", " mare nova holanda ", "MARE NOVA HOLANDA"),
    ],
)
def test_normalizar_localidade(
    localidade: str | None, unidade: str | None, esperado: str
) -> None:
    assert normalizar_localidade(localidade, unidade) == esperado


@pytest.mark.parametrize(
    "valor,esperado",
    [
        ("0000000000000022", "22"),
        ("0000000000000003", "3"),
        ("54", "54"),
        ("0", ""),
        ("0000", ""),
        ("", ""),
        (None, ""),
        ("S/N", "S/N"),
    ],
)
def test_normalizar_numero(valor: str | None, esperado: str) -> None:
    assert normalizar_numero(valor) == esperado


@pytest.mark.parametrize(
    "valor,esperado",
    [
        ("21061300", "21061-300"),
        ("05010000", "05010-000"),
        ("21061-300", "21061-300"),
        ("0", ""),
        ("", ""),
        (None, ""),
    ],
)
def test_formatar_cep(valor: str | None, esperado: str) -> None:
    assert formatar_cep(valor) == esperado


def test_montar_endereco_cadunico_unico_por_semente() -> None:
    campos = {
        "logradouro": "RUA JOAO SEVERINO",
        "numero": "32",
        "complemento": "",
        "complemento_adic": "CASA 2",
        "referencia": "",
        "localidade": "MARE NOVA HOLANDA",
    }
    # Mesma semente (mesmo endereço) => mesma junção, de forma reprodutível.
    assert montar_endereco_cadunico(campos, random.Random("k")) == (
        montar_endereco_cadunico(campos, random.Random("k"))
    )


def test_montar_endereco_cadunico_omite_campos_vazios() -> None:
    campos = {
        "logradouro": "RUA DO MEIO",
        "numero": "",
        "complemento": "",
        "complemento_adic": "",
        "referencia": "",
        "localidade": "MARE COMUNIDADE VILA DO PINHEIRO",
    }
    endereco = montar_endereco_cadunico(campos, random.Random("k"))
    assert "RUA DO MEIO" in endereco
    assert "MARE COMUNIDADE VILA DO PINHEIRO" in endereco
    assert "  " not in endereco


def test_cadunico_registrado() -> None:
    assert FONTES.get("cadunico") is FONTE_CADUNICO
