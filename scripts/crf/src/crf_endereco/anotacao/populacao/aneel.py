"""Populador das unidades consumidoras da ANEEL."""

from __future__ import annotations

from collections.abc import Iterator
from typing import ClassVar

import duckdb

from crf_endereco.anotacao.populacao.populador import Populador, municipios_csv
from crf_endereco.registro import Registro, montar_extras, texto


class PopuladorAneel(Populador):
    """Unidades Consumidoras PJ da ANEEL (BDGD): endereço concatenado + geo.

    A origem é o parquet consolidado da ANEEL (`aneel.py` gera
    `aneel_uc_pj.parquet`, ou um por classe: UCAT/UCMT/UCBT PJ). O endereço já
    vem bruto em `LGRD` (logradouro + número + complemento) e é mantido como
    veio; bairro, CEP, município/UF (resolvidos do código IBGE `MUN` via
    `municipios.csv`), CNAE e situação entram em `extras`, sem popular
    segmentos.
    """

    tipo = "aneel_uc_pj"
    rotulo = "ANEEL (Unidades Consumidoras PJ — BDGD)"
    TAM_LOTE: ClassVar[int] = 20_000

    CONSULTA: ClassVar[str] = """
        SELECT a.COD_ID_ENCR, a.PN_CON, a.LGRD, a.BRR, a.CEP, a.MUN,
               m.municipio, m.uf, a.CNAE, a.SIT_ATIV,
               a.POINT_X, a.POINT_Y
        FROM read_parquet(?) a
        LEFT JOIN read_csv(?, header = true) m
               ON try_cast(m.cod_ibge AS BIGINT) = a.MUN
        WHERE a.LGRD IS NOT NULL AND trim(a.LGRD) <> ''
    """

    def popular(
        self,
        conn: duckdb.DuckDBPyConnection,
    ) -> Iterator[Registro]:
        municipios = municipios_csv()
        if municipios is None:
            raise RuntimeError(
                "municipios.csv (cod_ibge, municipio, uf) não encontrado para "
                "resolver o código IBGE da ANEEL"
            )
        resultado = conn.execute(self.CONSULTA, [str(self.arquivo), str(municipios)])

        while True:
            linhas = resultado.fetchmany(self.TAM_LOTE)
            if not linhas:
                break
            for linha in linhas:
                (
                    cod_id,
                    pn_con,
                    lgrd,
                    brr,
                    cep,
                    mun,
                    municipio,
                    uf,
                    cnae,
                    situacao,
                    point_x,
                    point_y,
                ) = linha
                cep = texto(cep)
                cnae = texto(cnae)
                situacao = texto(situacao)
                yield Registro(
                    endereco=texto(lgrd),
                    extras=montar_extras(
                        texto(municipio),
                        texto(uf),
                        texto(brr),
                        banco="ANEEL (Unidades Consumidoras PJ)",
                        extras_adicionais=[
                            ("CEP", cep),
                            ("CNAE", cnae),
                            ("Situação", situacao),
                        ],
                    ),
                    meta={
                        "latitude": point_y,
                        "longitude": point_x,
                        "cod_ibge": mun,
                        "cep": cep or None,
                        "cnae": cnae or None,
                        "situacao": situacao or None,
                        "arquivo": str(self.arquivo),
                    },
                    origem=self.tipo,
                    origem_id=texto(cod_id) or texto(pn_con) or None,
                    municipio=texto(municipio),
                    uf=texto(uf),
                )
