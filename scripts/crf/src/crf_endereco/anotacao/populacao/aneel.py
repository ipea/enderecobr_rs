"""Base: unidades consumidoras PJ da ANEEL (BDGD)."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from crf_endereco.anotacao.populacao.populador import Fonte, parametros_municipios
from crf_endereco.registro import Registro, montar_extras, registro, texto

TIPO = "aneel_uc_pj"
ROTULO = "ANEEL (Unidades Consumidoras PJ — BDGD)"

# O endereco ja vem bruto em `LGRD` (logradouro + numero + complemento); bairro,
# CEP, municipio/UF (resolvidos do codigo IBGE `MUN`), CNAE e situacao entram
# so nas extras.
CONSULTA = """
    SELECT a.COD_ID_ENCR, a.PN_CON, a.LGRD, a.BRR, a.CEP, a.MUN,
           m.municipio, m.uf, a.CNAE, a.SIT_ATIV, a.POINT_X, a.POINT_Y
    FROM read_parquet(?) a
    LEFT JOIN read_csv(?, header = true) m
           ON try_cast(m.cod_ibge AS BIGINT) = a.MUN
    WHERE a.LGRD IS NOT NULL AND trim(a.LGRD) <> ''
"""


def registrar(linha: Sequence[Any], arquivo: Path, _aba: str | None) -> Registro:
    cod_id, pn_con, lgrd, brr, cep, mun, municipio, uf, cnae, situacao, x, y = linha
    return registro(
        endereco=lgrd,
        extras=montar_extras(
            texto(municipio),
            texto(uf),
            texto(brr),
            banco=ROTULO,
            extras_adicionais=[
                ("CEP", texto(cep)),
                ("CNAE", texto(cnae)),
                ("Situação", texto(situacao)),
            ],
        ),
        meta={
            "latitude": y,
            "longitude": x,
            "cod_ibge": mun,
            "cep": texto(cep) or None,
            "cnae": texto(cnae) or None,
            "situacao": texto(situacao) or None,
            "arquivo": str(arquivo),
        },
        origem=TIPO,
        origem_id=texto(cod_id) or texto(pn_con),
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
