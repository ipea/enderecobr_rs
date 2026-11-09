"""Base: Cadastro de Unidades Consumidoras (origem reservada)."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from crf_endereco.anotacao.populacao.populador import (
    Fonte,
    parametros_municipios,
    ultimo_campo,
)
from crf_endereco.registro import (
    Registro,
    montar_extras,
    registro,
    texto,
)
from crf_endereco.registro import (
    cep as cep_texto,
)

TIPO = "siase"
ROTULO = "Cadastro de Unidades Consumidoras"

# O endereco vem bruto em `DscEndereco` (campos separados por virgula, em
# quantidade variavel) e e mantido verbatim; o ultimo campo tambem e extraido
# como bairro. A identidade da base e reservada: so o descritor neutro vai para
# as extras, e os identificadores ficam no `meta` (que a LLM nao ve).
CONSULTA = """
    SELECT a.IdeCadNacionalDistribuicao, a.NumUC, a.DscEndereco,
           a.NumCEP, a.CodIbgeMunicipio, m.municipio, m.uf
    FROM read_parquet(?) a
    LEFT JOIN read_csv(?, header = true) m
           ON try_cast(m.cod_ibge AS BIGINT) = a.CodIbgeMunicipio
    WHERE a.DscEndereco IS NOT NULL AND trim(a.DscEndereco) <> ''
"""


def registrar(linha: Sequence[Any], arquivo: Path, _aba: str | None) -> Registro:
    ide_cad, num_uc, dsc_endereco, num_cep, cod_ibge, municipio, uf = linha
    endereco = texto(dsc_endereco)
    bairro = ultimo_campo(endereco)
    cep = cep_texto(num_cep)
    return registro(
        endereco=endereco,
        extras=montar_extras(
            texto(municipio),
            texto(uf),
            bairro,
            banco=ROTULO,
            extras_adicionais=[("CEP", cep)],
        ),
        meta={
            "ide_cad_nacional_distribuicao": texto(ide_cad),
            "num_uc": texto(num_uc),
            "cod_ibge": cod_ibge,
            "cep": cep or None,
            "bairro": bairro or None,
            "arquivo": str(arquivo),
        },
        origem=TIPO,
        origem_id=texto(ide_cad) or texto(num_uc),
        municipio=municipio,
        uf=uf,
    )


FONTE = Fonte(
    tipo=TIPO,
    rotulo=ROTULO,
    consulta=CONSULTA,
    registrar=registrar,
    parametros=parametros_municipios,
)
