"""Populador do Cadastro de Imoveis Rurais (CAFIR)."""

from __future__ import annotations

from collections.abc import Iterator
from typing import ClassVar

import duckdb

from crf_endereco.anotacao.populacao.populador import (
    Populador,
    RegistroEtiquetacao,
    limpar_texto,
    montar_extras,
)


class PopuladorCafir(Populador):
    """Imóveis rurais do CAFIR (Receita Federal): endereço espalhado em colunas.

    A origem é o Parquet consolidado do CAFIR (largura fixa convertida por
    `cafir.py`; ver `Layout Campos Dados Abertos Cafir.pdf`). Não há lat/long.
    O `endereco` é o logradouro bruto como está na base; município/UF, distrito
    e CEP, além do contexto do imóvel (nome, área, situação), entram só em
    `extras`, sem popular segmentos.
    """

    tipo = "cafir"
    rotulo = "CAFIR (Imóveis Rurais — Receita Federal)"
    TAM_LOTE: ClassVar[int] = 20_000

    CONSULTA: ClassVar[str] = """
        SELECT nirf, nome, logradouro, distrito, municipio, uf, cep,
               area_ha, incra, situacao, situacao_descricao
        FROM read_parquet(?)
        WHERE logradouro IS NOT NULL AND trim(logradouro) <> ''
    """

    def popular(
        self,
        conn: duckdb.DuckDBPyConnection,
    ) -> Iterator[RegistroEtiquetacao]:
        padrao = str(self.arquivo)
        if self.arquivo.is_dir():
            padrao = str(self.arquivo / "*.parquet")
        resultado = conn.execute(self.CONSULTA, [padrao])

        while True:
            linhas = resultado.fetchmany(self.TAM_LOTE)
            if not linhas:
                break
            for linha in linhas:
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
                    situacao_descricao,
                ) = linha
                nome = limpar_texto(nome)
                distrito = limpar_texto(distrito)
                municipio = limpar_texto(municipio)
                uf = limpar_texto(uf)
                cep = limpar_texto(cep)
                area = f"{area_ha:g} ha" if area_ha is not None else ""
                yield RegistroEtiquetacao(
                    endereco=limpar_texto(logradouro),
                    extras=montar_extras(
                        municipio,
                        uf,
                        None,
                        banco="CAFIR (Receita Federal)",
                        extras_adicionais=[
                            ("Nome do imóvel", nome),
                            ("Distrito", distrito),
                            ("CEP", cep),
                            ("Área", area),
                            ("Situação", limpar_texto(situacao_descricao)),
                        ],
                    ),
                    meta={
                        "nirf": limpar_texto(nirf),
                        "incra": limpar_texto(incra) or None,
                        "nome_imovel": nome,
                        "area_ha": area_ha,
                        "situacao": limpar_texto(situacao),
                        "situacao_descricao": limpar_texto(situacao_descricao),
                        "cep": cep or None,
                        "arquivo": str(self.arquivo),
                    },
                    origem=self.tipo,
                    origem_id=limpar_texto(nirf) or None,
                    municipio=municipio,
                    uf=uf,
                )
