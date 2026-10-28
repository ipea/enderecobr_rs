"""Base: CNEAS (entidades de assistencia social do MDS)."""

from __future__ import annotations

import random
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from crf_endereco.anotacao.populacao.populador import Fonte, rng_registro
from crf_endereco.registro import Registro, montar_extras, registro, texto

TIPO = "cneas"
ROTULO = "CNEAS (Entidades de Assistência Social — MDS)"

# Arranjos (ordem dos campos) para montar a linha bruta, com peso relativo. Os
# pesos espelham a frequencia em cadastros reais: o padrao "Correios"
# (municipio/UF/CEP ao fim) domina; variacoes raras entram com peso baixo.
ARRANJOS: tuple[tuple[str, float], ...] = (
    ("logradouro numero complemento bairro municipio uf cep", 3.0),
    ("logradouro numero complemento bairro municipio uf", 3.0),
    ("logradouro numero complemento bairro cep municipio uf", 1.5),
    ("logradouro numero complemento cep bairro municipio uf", 1.0),
    ("logradouro numero complemento bairro", 1.0),
    ("logradouro numero complemento municipio uf", 1.0),
    ("logradouro bairro numero complemento municipio uf", 1.0),
    ("municipio uf logradouro numero complemento", 0.5),
)

SEPARADORES: tuple[str, ...] = (", ", " ")

# Probabilidade de injetar o nome da entidade no texto (candidato a empreendimento).
PROB_NOME: float = 0.35

# Uma linha por entidade (o snapshot mais recente, `anomes` maximo).
CONSULTA = """
    SELECT cneas_cod_entidade_s AS cod_entidade,
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
           cneas_entidade_situacao_cadastro_s AS situacao
    FROM (
        SELECT *, row_number() OVER (
                   PARTITION BY cneas_cod_entidade_s ORDER BY anomes DESC
               ) AS rn
        FROM read_parquet(?)
    )
    WHERE rn = 1
      AND cneas_entidade_endereco_logradouro_s IS NOT NULL
      AND trim(cneas_entidade_endereco_logradouro_s) <> ''
"""


def montar_endereco(campos: dict[str, str], nome: str, rnd: random.Random) -> str:
    """Junta os campos segmentados numa linha bruta.

    Sorteia um arranjo de campo (por peso) e um separador, descarta os campos
    vazios e, com `PROB_NOME`, injeta `nome` numa posicao aleatoria entre os
    campos (candidato a `empreendimento`). Os valores vao verbatim: a LLM
    corrige a segmentacao.
    """
    formato = rnd.choices(
        [arranjo for arranjo, _ in ARRANJOS],
        weights=[peso for _, peso in ARRANJOS],
    )[0].split()
    separador = rnd.choice(SEPARADORES)

    valores = [campos[campo] for campo in formato if campos.get(campo)]
    if nome and rnd.random() < PROB_NOME:
        valores.insert(rnd.randint(0, len(valores)), nome)
    return separador.join(valores)


def registrar(linha: Sequence[Any], arquivo: Path, _aba: str | None) -> Registro:
    (
        cod_entidade,
        cnpj,
        razao_social,
        fantasia,
        logradouro,
        numero,
        complemento,
        bairro,
        cep,
        municipio,
        uf,
        situacao,
    ) = linha
    nome = texto(fantasia) or texto(razao_social)
    campos = {
        "logradouro": texto(logradouro),
        "numero": texto(numero),
        "complemento": texto(complemento),
        "bairro": texto(bairro),
        "cep": texto(cep),
        "municipio": texto(municipio),
        "uf": texto(uf),
    }
    rnd = rng_registro(texto(cod_entidade) or nome or campos["logradouro"])
    return registro(
        endereco=montar_endereco(campos, nome, rnd),
        extras=montar_extras(
            None,
            None,
            None,
            banco=ROTULO,
            extras_adicionais=[
                ("Entidade", nome),
                ("Situação", texto(situacao)),
            ],
        ),
        meta={
            "cod_entidade": texto(cod_entidade),
            "cnpj": texto(cnpj) or None,
            "razao_social": texto(razao_social),
            "nome_fantasia": texto(fantasia),
            "municipio": campos["municipio"],
            "uf": campos["uf"],
            "cep": campos["cep"] or None,
            "situacao": texto(situacao),
            "arquivo": str(arquivo),
        },
        origem=TIPO,
        origem_id=cod_entidade,
        municipio=campos["municipio"],
        uf=campos["uf"],
    )


FONTE = Fonte(tipo=TIPO, rotulo=ROTULO, consulta=CONSULTA, registrar=registrar)
