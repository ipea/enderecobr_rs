"""Populador do Cadastro Unico (MDS)."""

from __future__ import annotations

import random
from collections.abc import Iterator
from typing import Any, ClassVar

import duckdb

from crf_endereco.anotacao.populacao.populador import (
    Populador,
    municipios_csv,
    rng_registro,
)
from crf_endereco.registro import Registro, cep, montar_extras, numero, texto

# Sufixos de `no_unidade_territorial_fam` que apenas repetem/rotulam o bairro,
# sem acrescentar submidade útil.
SUFIXOS_UNIDADE_TERRITORIAL_RUIDO: frozenset[str] = frozenset({"OUTROS", "AREA NORMAL"})

# Descritor da base no campo `extras` (vai no prompt da LLM). O vínculo real
# com a origem fica só na coluna interna `origem`.
BANCO_CADUNICO: str = "Cadastro Único (MDS)"

# Arranjos (ordem dos campos) para recompôr a linha bruta do CadÚnico, com
# peso relativo. O cadastro já traz os campos separados; a linha imita um
# endereço real: logradouro → número → complemento(s) → referência →
# localidade. Os pesos espelham o padrão dominante (localidade ao fim).
ARRANJOS_CADUNICO: tuple[tuple[str, float], ...] = (
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

SEPARADORES_CADUNICO: tuple[str, ...] = (", ", " ")


def normalizar_numero(valor: Any) -> str:
    """Número do logradouro sem os zeros à esquerda.

    O cadastro grava o número zero-padded (`000…22`); número ausente (`0`,
    `000…0` ou vazio) devolve ''. Valores não numéricos (ex.: `S/N`) ficam
    como vieram.
    """
    return numero(valor)


def formatar_cep(valor: Any) -> str:
    """CEP com hífen ('21061-300') a partir dos 8 dígitos do cadastro."""
    digitos = "".join(ch for ch in cep(valor) if ch.isdigit())
    return f"{digitos[:5]}-{digitos[5:]}" if len(digitos) == 8 else digitos


def normalizar_localidade(localidade: Any, unidade_territorial: Any) -> str:
    """Melhor localidade do cadastro: o bairro enriquecido pela submidade.

    `no_unidade_territorial_fam` é mais completo (bairro + submidade, ex.:
    'MARE NOVA HOLANDA' = bairro Maré + favela Nova Holanda), mas heterogêneo:
    fora de RJ/DF costuma trazer o CRAS/unidade administrativa ou o próprio
    município — que NÃO é localidade. Por isso só se aproveita o excedente
    quando ele ESTENDE o bairro (`no_localidade_fam`); sufixo vazio, de ruído
    ('OUTROS', 'AREA NORMAL') ou o bairro repetido caem para o bairro puro.
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


def montar_endereco_cadunico(campos: dict[str, str], rnd: random.Random) -> str:
    """Junta os campos segmentados do CadÚnico numa linha bruta.

    Sorteia um arranjo de campo (por peso) e um separador, descarta os campos
    vazios. Diferente do CNEAS, não há nome de empreendimento: é um domicílio.
    """
    formato = rnd.choices(
        [arranjo for arranjo, _ in ARRANJOS_CADUNICO],
        weights=[peso for _, peso in ARRANJOS_CADUNICO],
    )[0].split()
    separador = rnd.choice(SEPARADORES_CADUNICO)
    valores = [campos[campo] for campo in formato if campos.get(campo)]
    return separador.join(valores)


class PopuladorCadUnico(Populador):
    """CadÚnico (MDS): endereço por família, já segmentado em campos.

    Origem: parquet mensal (`cadunico_fam_YYYYMM.parquet`), uma linha por
    família. Mantém-se **uma linha por família** e recompõe-se a linha bruta
    juntando os campos segmentados (`montar_endereco_cadunico`): logradouro
    (tipo + título + nome), número, complemento(s), a localidade (ver
    `normalizar_localidade`) e a referência local. O município/UF vêm do
    código IBGE (`cd_ibge_cadastro`) via `municipios.csv` e, junto do CEP,
    entram só em `extras`/`meta` — NÃO no endereço. Os valores vão verbatim
    (só o número e o CEP são normalizados: o cadastro os grava padded/sem
    hífen).

    Privacidade: base restrita. Só o endereço e o contexto geográfico são
    exportados; identificadores e dados da família (renda, composição, CPF do
    entrevistador, etc.) **não** entram em `extras`, `meta` nem `origem_id`.
    """

    tipo = "cadunico"
    rotulo = "Cadastro Único (MDS)"
    TAM_LOTE: ClassVar[int] = 20_000

    CONSULTA: ClassVar[str] = """
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

    def popular(
        self,
        conn: duckdb.DuckDBPyConnection,
    ) -> Iterator[Registro]:
        municipios = municipios_csv()
        if municipios is None:
            raise RuntimeError(
                "municipios.csv (cod_ibge, municipio, uf) não encontrado para "
                "resolver o código IBGE do CadÚnico"
            )
        resultado = conn.execute(self.CONSULTA, [str(self.arquivo), str(municipios)])

        while True:
            linhas = resultado.fetchmany(self.TAM_LOTE)
            if not linhas:
                break
            for linha in linhas:
                (
                    tip_logradouro,
                    tit_logradouro,
                    nome_logradouro,
                    numero,
                    complemento,
                    complemento_adic,
                    referencia,
                    cep,
                    localidade,
                    unidade_territorial,
                    cod_ibge,
                    municipio,
                    uf,
                ) = linha
                logradouro = " ".join(
                    parte
                    for parte in (
                        texto(tip_logradouro),
                        texto(tit_logradouro),
                        texto(nome_logradouro),
                    )
                    if parte
                )
                localidade = normalizar_localidade(localidade, unidade_territorial)
                cep = formatar_cep(cep)
                municipio = texto(municipio)
                uf = texto(uf)
                campos = {
                    "logradouro": logradouro,
                    "numero": normalizar_numero(numero),
                    "complemento": texto(complemento),
                    "complemento_adic": texto(complemento_adic),
                    "referencia": texto(referencia),
                    "localidade": localidade,
                }
                # Semente pelo próprio endereço: sem identificador de família
                # (privacidade) e garante a mesma junção para endereço igual.
                rnd = rng_registro("|".join(v for v in campos.values() if v))
                yield Registro(
                    endereco=montar_endereco_cadunico(campos, rnd),
                    extras=montar_extras(
                        municipio,
                        uf,
                        localidade or None,
                        banco=BANCO_CADUNICO,
                        extras_adicionais=[("CEP", cep)],
                    ),
                    meta={
                        "cod_ibge": cod_ibge,
                        "cep": cep or None,
                        "localidade": localidade or None,
                        "unidade_territorial": (texto(unidade_territorial) or None),
                        "arquivo": str(self.arquivo),
                    },
                    origem=self.tipo,
                    origem_id=None,
                    municipio=municipio,
                    uf=uf,
                )
