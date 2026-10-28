"""Populador do SIASE (assistencia social)."""

from __future__ import annotations

from collections.abc import Iterator
from typing import ClassVar

import duckdb

from crf_endereco.anotacao.populacao.populador import (
    Populador,
    municipios_csv,
    ultimo_campo,
)
from crf_endereco.registro import Registro, montar_extras, texto
from crf_endereco.registro import cep as cep_texto


class PopuladorSiase(Populador):
    """Cadastro de Unidades Consumidoras (origem reservada): endereço bruto.

    Origem: um parquet mensal particionado (`ano=YYYY/mes=MM`; passe o arquivo
    ou o diretório), uma linha por cadastro. O endereço vem bruto em
    `DscEndereco` (campos separados por vírgula, em quantidade variável) e é
    mantido **verbatim**; o último campo também é extraído como bairro, junto
    do CEP e do município/UF (resolvidos do código IBGE `CodIbgeMunicipio` via
    `municipios.csv`).

    A identidade da base é reservada: **não** entra em `extras` (que vai no
    prompt da LLM) — ali só há um descritor neutro. O vínculo com a origem fica
    na coluna interna `origem` e nos identificadores do `meta`
    (`IdeCadNacionalDistribuicao`/`NumUC`), que a LLM não vê.
    """

    tipo = "siase"
    rotulo = "Cadastro de Unidades Consumidoras"
    TAM_LOTE: ClassVar[int] = 20_000
    BANCO: ClassVar[str] = "Cadastro de Unidades Consumidoras"

    CONSULTA: ClassVar[str] = """
        SELECT a.IdeCadNacionalDistribuicao, a.NumUC, a.DscEndereco,
               a.NumCEP, a.CodIbgeMunicipio, m.municipio, m.uf
        FROM read_parquet(?) a
        LEFT JOIN read_csv(?, header = true) m
               ON try_cast(m.cod_ibge AS BIGINT) = a.CodIbgeMunicipio
        WHERE a.DscEndereco IS NOT NULL AND trim(a.DscEndereco) <> ''
    """

    def popular(
        self,
        conn: duckdb.DuckDBPyConnection,
    ) -> Iterator[Registro]:
        municipios = municipios_csv()
        if municipios is None:
            raise RuntimeError(
                "municipios.csv (cod_ibge, municipio, uf) não encontrado para "
                "resolver o código IBGE da origem"
            )
        padrao = str(self.arquivo)
        if self.arquivo.is_dir():
            padrao = str(self.arquivo / "*.parquet")
        resultado = conn.execute(self.CONSULTA, [padrao, str(municipios)])

        while True:
            linhas = resultado.fetchmany(self.TAM_LOTE)
            if not linhas:
                break
            for linha in linhas:
                (
                    ide_cad,
                    num_uc,
                    dsc_endereco,
                    num_cep,
                    cod_ibge,
                    municipio,
                    uf,
                ) = linha
                endereco = texto(dsc_endereco)
                bairro = ultimo_campo(endereco)
                cep = cep_texto(num_cep)
                municipio = texto(municipio)
                uf = texto(uf)
                ide_cad = texto(ide_cad)
                num_uc = texto(num_uc)
                yield Registro(
                    endereco=endereco,
                    extras=montar_extras(
                        municipio,
                        uf,
                        bairro,
                        banco=self.BANCO,
                        extras_adicionais=[("CEP", cep)],
                    ),
                    meta={
                        "ide_cad_nacional_distribuicao": ide_cad,
                        "num_uc": num_uc,
                        "cod_ibge": cod_ibge,
                        "cep": cep or None,
                        "bairro": bairro or None,
                        "arquivo": str(self.arquivo),
                    },
                    origem=self.tipo,
                    origem_id=ide_cad or num_uc or None,
                    municipio=municipio,
                    uf=uf,
                )
