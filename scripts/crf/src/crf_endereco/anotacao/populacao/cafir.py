"""Base: Cadastro de Imoveis Rurais (CAFIR)."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from crf_endereco.anotacao.populacao.populador import Fonte
from crf_endereco.registro import Registro, montar_extras, registro, texto

TIPO = "cafir"
ROTULO = "CAFIR (Imóveis Rurais — Receita Federal)"

# Sem lat/long: o logradouro bruto e o endereco; o contexto do imovel vai em extras.
CONSULTA = """
    SELECT nirf, nome, logradouro, distrito, municipio, uf, cep,
           area_ha, incra, situacao, situacao_descricao
    FROM read_parquet(?)
    WHERE logradouro IS NOT NULL AND trim(logradouro) <> ''
"""


def registrar(linha: Sequence[Any], arquivo: Path, _aba: str | None) -> Registro:
    (
        nirf,
        nome,
        logradouro,
        distrito,
        municipio,
        uf,
        cep,
        area_ha,
        incra,
        situacao,
        descricao,
    ) = linha
    area = f"{area_ha:g} ha" if area_ha is not None else ""
    return registro(
        endereco=logradouro,
        extras=montar_extras(
            texto(municipio),
            texto(uf),
            None,
            banco=ROTULO,
            extras_adicionais=[
                ("Nome do imóvel", texto(nome)),
                ("Distrito", texto(distrito)),
                ("CEP", texto(cep)),
                ("Área", area),
                ("Situação", texto(descricao)),
            ],
        ),
        meta={
            "nirf": texto(nirf),
            "incra": texto(incra) or None,
            "nome_imovel": texto(nome),
            "area_ha": area_ha,
            "situacao": texto(situacao),
            "situacao_descricao": texto(descricao),
            "cep": texto(cep) or None,
            "arquivo": str(arquivo),
        },
        origem=TIPO,
        origem_id=nirf,
        municipio=municipio,
        uf=uf,
    )


FONTE = Fonte(tipo=TIPO, rotulo=ROTULO, consulta=CONSULTA, registrar=registrar)
