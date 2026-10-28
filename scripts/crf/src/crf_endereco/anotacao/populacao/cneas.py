"""Populador do CNEAS (entidades de assistencia social)."""

from __future__ import annotations

import random
from collections.abc import Iterator
from typing import ClassVar

import duckdb

from crf_endereco.anotacao.populacao.populador import Populador, rng_registro
from crf_endereco.registro import Registro, montar_extras, texto

# Arranjos (ordem dos campos) para montar a linha bruta do CNEAS, com peso
# relativo. Os pesos espelham a frequência em cadastros reais: o padrão
# "Correios" (município/UF/CEP ao fim) domina; variações raras (CEP antes do
# bairro, município na frente) entram com peso baixo. Ver `montar_endereco_cneas`.
ARRANJOS_CNEAS: tuple[tuple[str, float], ...] = (
    ("logradouro numero complemento bairro municipio uf cep", 3.0),
    ("logradouro numero complemento bairro municipio uf", 3.0),
    ("logradouro numero complemento bairro cep municipio uf", 1.5),
    ("logradouro numero complemento cep bairro municipio uf", 1.0),
    ("logradouro numero complemento bairro", 1.0),
    ("logradouro numero complemento municipio uf", 1.0),
    ("logradouro bairro numero complemento municipio uf", 1.0),
    ("municipio uf logradouro numero complemento", 0.5),
)

SEPARADORES_CNEAS: tuple[str, ...] = (", ", " ")

# Probabilidade de injetar o nome da entidade no texto (candidato a empreendimento).
PROB_NOME_CNEAS: float = 0.35


def montar_endereco_cneas(campos: dict[str, str], nome: str, rnd: random.Random) -> str:
    """Junta os campos segmentados do CNEAS numa linha bruta.

    Sorteia um arranjo de campo (por peso relativo) e um separador, descarta os
    campos vazios e, com `PROB_NOME_CNEAS`, injeta `nome` numa posição aleatória
    entre os campos (candidato a `empreendimento`, em qualquer ponto do texto).
    Os valores vão verbatim: a LLM corrige a segmentação.
    """
    formato = rnd.choices(
        [arranjo for arranjo, _ in ARRANJOS_CNEAS],
        weights=[peso for _, peso in ARRANJOS_CNEAS],
    )[0].split()
    separador = rnd.choice(SEPARADORES_CNEAS)

    valores = [campos[campo] for campo in formato if campos.get(campo)]

    if nome and rnd.random() < PROB_NOME_CNEAS:
        valores.insert(rnd.randint(0, len(valores)), nome)

    return separador.join(valores)


class PopuladorCneas(Populador):
    """CNEAS (Entidades de Assistência Social do MDS): endereço em campos separados.

    Origem: parquet consolidado por `cneas.py` (snapshots mensais). Mantém-se
    **uma linha por entidade** (o snapshot mais recente, `anomes` máximo) e a
    linha bruta é montada juntando os campos segmentados
    (`montar_endereco_cneas`). Município/UF/bairro/CEP vão no endereço (viram
    segmentos); o nome da entidade é injetado aleatoriamente no texto
    (candidato a `empreendimento`) e também em `extras`. Os valores vão
    verbatim: a LLM corrige a segmentação na rotulagem.
    """

    tipo = "cneas"
    rotulo = "CNEAS (Entidades de Assistência Social — MDS)"
    TAM_LOTE: ClassVar[int] = 20_000

    CONSULTA: ClassVar[str] = """
        SELECT * EXCLUDE (rn)
        FROM (
            SELECT
                cneas_cod_entidade_s AS cod_entidade,
                cneas_entidade_numero_cnpj_s AS cnpj,
                cneas_entidade_razao_social_s AS razao_social,
                cneas_entidade_nome_fantasia_s AS nome_fantasia,
                cneas_entidade_endereco_logradouro_s AS logradouro,
                cneas_entidade_endereco_numero_s AS numero,
                cneas_entidade_endereco_complemento_s AS complemento,
                cneas_entidade_endereco_bairro_s AS bairro,
                cneas_entidade_endereco_cep_s AS cep,
                cneas_entidade_nome_municipio_s AS municipio,
                cneas_entidade_sigla_uf_s AS uf,
                cneas_entidade_situacao_cadastro_s AS situacao,
                row_number() OVER (
                    PARTITION BY cneas_cod_entidade_s
                    ORDER BY anomes DESC
                ) AS rn
            FROM read_parquet(?)
        )
        WHERE rn = 1
          AND logradouro IS NOT NULL AND trim(logradouro) <> ''
    """

    def popular(
        self,
        conn: duckdb.DuckDBPyConnection,
    ) -> Iterator[Registro]:
        resultado = conn.execute(self.CONSULTA, [str(self.arquivo)])

        while True:
            linhas = resultado.fetchmany(self.TAM_LOTE)
            if not linhas:
                break
            for linha in linhas:
                (
                    cod_entidade,
                    cnpj,
                    razao_social,
                    nome_fantasia,
                    logradouro,
                    numero,
                    complemento,
                    bairro,
                    cep,
                    municipio,
                    uf,
                    situacao,
                ) = linha
                cod_entidade = texto(cod_entidade)
                razao_social = texto(razao_social)
                nome_fantasia = texto(nome_fantasia)
                nome = nome_fantasia or razao_social
                campos = {
                    "logradouro": texto(logradouro),
                    "numero": texto(numero),
                    "complemento": texto(complemento),
                    "bairro": texto(bairro),
                    "cep": texto(cep),
                    "municipio": texto(municipio),
                    "uf": texto(uf),
                }
                rnd = rng_registro(cod_entidade or nome or campos["logradouro"])
                yield Registro(
                    endereco=montar_endereco_cneas(campos, nome, rnd),
                    extras=montar_extras(
                        None,
                        None,
                        None,
                        banco="CNEAS (Entidades de Assistência Social)",
                        extras_adicionais=[
                            ("Entidade", nome),
                            ("Situação", texto(situacao)),
                        ],
                    ),
                    meta={
                        "cod_entidade": cod_entidade,
                        "cnpj": texto(cnpj) or None,
                        "razao_social": razao_social,
                        "nome_fantasia": nome_fantasia,
                        "municipio": campos["municipio"],
                        "uf": campos["uf"],
                        "cep": campos["cep"] or None,
                        "situacao": texto(situacao),
                        "arquivo": str(self.arquivo),
                    },
                    origem=self.tipo,
                    origem_id=cod_entidade or None,
                    municipio=campos["municipio"],
                    uf=campos["uf"],
                )
