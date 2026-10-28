"""Base: Cadastro Unico (MDS)."""

from __future__ import annotations

import random
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from crf_endereco.anotacao.populacao.populador import (
    Fonte,
    parametros_municipios,
    rng_registro,
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
from crf_endereco.registro import (
    numero as sem_zeros,
)

TIPO = "cadunico"
ROTULO = "Cadastro Único (MDS)"

# Sufixos de `no_unidade_territorial_fam` que apenas repetem/rotulam o bairro.
SUFIXOS_UNIDADE_TERRITORIAL_RUIDO: frozenset[str] = frozenset({"OUTROS", "AREA NORMAL"})

# Arranjos (ordem dos campos) para recompor a linha bruta, com peso relativo: a
# linha imita um endereco real (logradouro -> numero -> complemento(s) ->
# referencia -> localidade), que e o padrao dominante.
ARRANJOS: tuple[tuple[str, float], ...] = (
    ("logradouro numero complemento complemento_adic localidade referencia", 3.0),
    ("logradouro numero complemento complemento_adic localidade", 2.0),
    ("logradouro numero complemento localidade referencia", 1.5),
    ("logradouro numero complemento complemento_adic referencia localidade", 1.5),
    ("logradouro numero complemento localidade", 1.5),
    ("logradouro numero complemento_adic localidade", 1.0),
    ("logradouro numero referencia localidade", 0.5),
    ("logradouro numero complemento complemento_adic", 0.5),
    ("localidade logradouro numero complemento", 0.5),
)

SEPARADORES: tuple[str, ...] = (", ", " ")

# Uma linha por familia; o cadastro traz os campos separados e o municipio/UF
# vem do codigo IBGE (`cd_ibge_cadastro`) via `municipios.csv`.
CONSULTA = """
    SELECT
        a.no_tip_logradouro_fam AS tip_logradouro,
        a.no_tit_logradouro_fam AS tit_logradouro,
        a.no_logradouro_fam AS nome_logradouro,
        a.nu_logradouro_fam AS numero,
        a.ds_complemento_fam AS complemento,
        a.ds_complemento_adic_fam AS complemento_adic,
        a.ds_referencia_local_fam AS referencia,
        a.nu_cep_logradouro_fam AS cep,
        a.no_localidade_fam AS localidade,
        a.no_unidade_territorial_fam AS unidade_territorial,
        a.cd_ibge_cadastro AS cod_ibge,
        m.municipio AS municipio,
        m.uf AS uf
    FROM read_parquet(?) a
    LEFT JOIN read_csv(?, header = true) m
           ON try_cast(m.cod_ibge AS BIGINT) = a.cd_ibge_cadastro
    WHERE a.no_logradouro_fam IS NOT NULL
      AND trim(a.no_logradouro_fam) <> ''
"""


def formatar_cep(valor: Any) -> str:
    """CEP com hifen ('21061-300') a partir dos 8 digitos do cadastro."""
    digitos = "".join(ch for ch in cep_texto(valor) if ch.isdigit())
    return f"{digitos[:5]}-{digitos[5:]}" if len(digitos) == 8 else digitos


def normalizar_localidade(localidade: Any, unidade_territorial: Any) -> str:
    """Melhor localidade do cadastro: o bairro enriquecido pela submidade.

    `no_unidade_territorial_fam` e mais completo (bairro + submidade, ex.:
    'MARE NOVA HOLANDA' = bairro Mare + favela Nova Holanda), mas heterogeneo:
    fora de RJ/DF costuma trazer o CRAS/unidade administrativa ou o proprio
    municipio - que NAO e localidade. Por isso so se aproveita o excedente
    quando ele ESTENDE o bairro; sufixo vazio, de ruido ('OUTROS', 'AREA
    NORMAL') ou o bairro repetido caem para o bairro puro.
    """
    loc = texto(localidade).upper()
    ut = texto(unidade_territorial).upper()
    if not loc:
        return ut
    if not ut or ut == loc:
        return loc
    if ut.startswith(loc + " "):
        sufixo = ut[len(loc) + 1 :].strip()
        if not sufixo or sufixo in SUFIXOS_UNIDADE_TERRITORIAL_RUIDO or sufixo == loc:
            return loc
        return ut
    return loc


def normalizar_numero(valor: Any) -> str:
    """Numero do logradouro sem os zeros a esquerda (ausente vira '')."""
    return sem_zeros(valor)


def montar_endereco(campos: dict[str, str], rnd: random.Random) -> str:
    """Junta os campos segmentados numa linha bruta (sem empreendimento: e um domicilio)."""
    formato = rnd.choices(
        [arranjo for arranjo, _ in ARRANJOS],
        weights=[peso for _, peso in ARRANJOS],
    )[0].split()
    separador = rnd.choice(SEPARADORES)
    valores = [campos[campo] for campo in formato if campos.get(campo)]
    return separador.join(valores)


def registrar(linha: Sequence[Any], arquivo: Path, _aba: str | None) -> Registro:
    (
        tip,
        titulo,
        nome_logradouro,
        numero,
        complemento,
        complemento_adic,
        referencia,
        cep,
        localidade,
        unidade,
        cod_ibge,
        municipio,
        uf,
    ) = linha
    localidade = normalizar_localidade(localidade, unidade)
    cep = formatar_cep(cep)
    campos = {
        "logradouro": " ".join(
            parte
            for parte in (texto(tip), texto(titulo), texto(nome_logradouro))
            if parte
        ),
        "numero": sem_zeros(numero),
        "complemento": texto(complemento),
        "complemento_adic": texto(complemento_adic),
        "referencia": texto(referencia),
        "localidade": localidade,
    }
    # Semente pelo proprio endereco: sem identificador de familia (privacidade) e
    # garante a mesma juncao para endereco igual.
    rnd = rng_registro("|".join(valor for valor in campos.values() if valor))
    return registro(
        endereco=montar_endereco(campos, rnd),
        extras=montar_extras(
            texto(municipio),
            texto(uf),
            localidade or None,
            banco=ROTULO,
            extras_adicionais=[("CEP", cep)],
        ),
        meta={
            "cod_ibge": cod_ibge,
            "cep": cep or None,
            "localidade": localidade or None,
            "unidade_territorial": texto(unidade) or None,
            "arquivo": str(arquivo),
        },
        origem=TIPO,
        origem_id=None,
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
