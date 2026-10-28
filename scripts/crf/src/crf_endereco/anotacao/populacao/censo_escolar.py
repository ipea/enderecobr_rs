"""Base: escolas do Censo Escolar (INEP)."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from crf_endereco.anotacao.populacao.populador import Fonte
from crf_endereco.registro import Registro, decimal, montar_extras, registro, texto

TIPO = "censo_escolar"
ROTULO = "Censo Escolar (INEP)"

# Valores de "Localidade Diferenciada" sem conteudo util (nao viram extras).
IGNORAR_LOCALIDADE = frozenset(
    valor.casefold()
    for valor in (
        "A escola não está em área de localização diferenciada",
        "Não Informado",
    )
)

# O endereco ja vem bruto (com CEP e "Municipio - UF" ao fim) e e mantido como veio.
CONSULTA = """
    SELECT "Escola", "Código INEP", "UF", "Município",
           "Localidade Diferenciada", "Dependência Administrativa",
           "Endereço", "Latitude", "Longitude"
    FROM read_csv(?, header = true, all_varchar = true)
    WHERE "Endereço" IS NOT NULL AND trim("Endereço") <> ''
"""


def limpar_localidade(valor: Any) -> str:
    """Descarta marcadores sem conteudo util de localidade diferenciada."""
    bruto = texto(valor)
    return "" if bruto.casefold() in IGNORAR_LOCALIDADE else bruto


def registrar(linha: Sequence[Any], arquivo: Path, _aba: str | None) -> Registro:
    escola, codigo_inep, uf, municipio, localidade, dependencia, endereco, lat, lon = (
        linha
    )
    return registro(
        endereco=endereco,
        extras=montar_extras(
            texto(municipio),
            texto(uf),
            None,
            banco=ROTULO,
            extras_adicionais=[
                ("Escola", texto(escola)),
                ("Dependência Administrativa", texto(dependencia)),
                ("Localidade Diferenciada", limpar_localidade(localidade)),
            ],
        ),
        meta={
            "latitude": decimal(lat),
            "longitude": decimal(lon),
            "escola": texto(escola),
            "dependencia_administrativa": texto(dependencia),
            "localidade_diferenciada": limpar_localidade(localidade) or None,
            "arquivo": str(arquivo),
        },
        origem=TIPO,
        origem_id=codigo_inep,
        municipio=municipio,
        uf=uf,
    )


FONTE = Fonte(tipo=TIPO, rotulo=ROTULO, consulta=CONSULTA, registrar=registrar)
