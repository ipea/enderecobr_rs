#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "duckdb>=1.4.1",
#     "rapidfuzz",
#     "rich",
#     "tqdm",
#     "typer",
# ]
# ///
"""Popula o dataset inicial que será etiquetado pela LLM (`etiquetar.py`).

Cria/append um SQLite com um endereço bruto por linha, sua "extra info" e
metadados. Cada `tipo_dataset` chaveia um populador, que sabe ler a origem
(xlsx/csv/parquet) via DuckDB, montar `endereco`/`extras`/`meta`/`origem` e
sortear uma amostra.

Uso:
    uv run dataset_etiquetacao.py imoveis_uniao ORIGEM.xlsx destino.db -n 1000 --seed 42
    uv run dataset_etiquetacao.py censo_escolar ESCOLAS.csv destino.db -n 1000
    uv run dataset_etiquetacao.py cafir cafir_D61001.parquet destino.db -n 1000
    uv run dataset_etiquetacao.py aneel_uc_pj aneel_uc_pj.parquet destino.db -n 1000
    uv run dataset_etiquetacao.py cneas cneas_entidades_2026.parquet destino.db -n 1000

Notas:
- A origem é lida com DuckDB (streaming, um único passe); o destino é
  escrito com `sqlite3` (append).
- O filtro de diversidade (`--similaridade-maxima`) usa rapidfuzz (escala
  0–100) contra os endereços já presentes no banco.
- A amostra é construída com reservoir sampling sobre o stream (memória
  constante, reprodutível via `--seed`): pede-se o tamanho exato e, havendo
  endereços diversos suficientes, a amostra sai cheia.
"""

from __future__ import annotations

import hashlib
import json
import random
import sqlite3
import time
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, ClassVar

import duckdb
import tqdm
import typer
from rapidfuzz import fuzz, process
from rich.console import Console

console = Console()


# --- Modelo ---------------------------------------------------------------


@dataclass
class RegistroEtiquetacao:
    """Uma linha do dataset a etiquetar, antes de virar registro no SQLite."""

    endereco: str
    extras: str
    meta: dict[str, Any]
    origem: str
    origem_id: str | None = None


# --- Filtro de diversidade ------------------------------------------------


class FiltroDiversidade(ABC):
    """Decide se um endereço sorteado entra no dataset (para aumentar a diversidade)."""

    @abstractmethod
    def aceitar(self, endereco: str) -> bool:
        """True se `endereco` pode entrar no dataset (não fere a diversidade)."""


class SemFiltroDiversidade(FiltroDiversidade):
    """Aceita tudo — usado quando nenhum limiar de diversidade é informado."""

    def aceitar(self, endereco: str) -> bool:
        return True


class FiltroDiversidadeFuzzy(FiltroDiversidade):
    """Descarta sorteados parecidos demais com endereços já aceitos (rapidfuzz).

    Compara cada candidato com os endereços já presentes (baseline do banco +
    aceitos nesta rodada) e rejeita quando a similaridade alcança o limiar.
    `similaridade_maxima` e `distancia_minima` são complementares, na escala
    0–100 do rapidfuzz (`distancia = 100 - similaridade`).
    """

    def __init__(
        self,
        aceitos: Iterable[str] = (),
        *,
        similaridade_maxima: float | None = None,
    ) -> None:
        self.aceitos: list[str] = list(aceitos)
        self.limite = 0.0
        if similaridade_maxima is not None:
            self.limite = max(self.limite, similaridade_maxima)

    def aceitar(self, endereco: str) -> bool:
        # `score_cutoff` corta cedo: só interessa um match >= limite.
        if process.extractOne(
            endereco,
            self.aceitos,
            scorer=fuzz.token_sort_ratio,
            score_cutoff=self.limite,
        ):
            return False
        self.aceitos.append(endereco)
        return True


# --- Populadores ----------------------------------------------------------


def converter_float(valor: Any) -> float | None:
    """Converte números com vírgula decimal (ex.: '-8,0962257') em float."""
    if valor is None:
        return None
    try:
        return float(str(valor).replace(",", "."))
    except ValueError:
        return None


def limpar_texto(valor: Any) -> str:
    """Normaliza um valor textual da origem (None -> '', sem espaços nas pontas)."""
    if valor is None:
        return ""
    return str(valor).strip()


def montar_extras(
    municipio: str | None,
    uf: str | None,
    bairro: str | None,
    *,
    banco: str,
    extras_adicionais: Iterable[tuple[str, str]] = (),
) -> str:
    """Monta a 'extra info' (contexto; não popula segmentos).

    `extras_adicionais` são pares (rótulo, valor) específicos de cada origem,
    gravados entre o bairro e o banco; valores vazios são omitidos.
    """
    linhas: list[str] = []
    municipio_uf = "/".join(p for p in (municipio, uf) if p)
    if municipio_uf:
        linhas.append(f"Municipio: {municipio_uf}")
    if bairro:
        linhas.append(f"Bairro: {bairro}")
    for rotulo, valor in extras_adicionais:
        if valor:
            linhas.append(f"{rotulo}: {valor}")
    if banco:
        linhas.append(f"Banco de Dados: {banco}")
    return "\n".join(linhas)


class Populador(ABC):
    """Lê uma origem e rende registros prontos para o dataset."""

    tipo: ClassVar[str]
    rotulo: ClassVar[str]

    def __init__(self, arquivo: Path, aba: str | None = None) -> None:
        self.arquivo = arquivo
        self.aba = aba

    @abstractmethod
    def popular(
        self,
        conn: duckdb.DuckDBPyConnection,
    ) -> Iterator[RegistroEtiquetacao]:
        """Percorre a origem em streaming, rendendo um registro por linha."""


class PopuladorImoveisUniao(Populador):
    """Imóveis da União (SPU): endereço já concatenado + geo.

    A consulta é um literal com placeholders (a extensão `excel` e o caminho
    entram como parâmetros, sem montar SQL com dados do usuário). A origem é
    percorrida em streaming, em lotes; a amostragem e o filtro acontecem
    depois, sobre o stream (ver `amostrar_reservatorio`).
    """

    tipo = "imoveis_uniao"
    rotulo = "Imóveis da União (SPU)"
    TAM_LOTE: ClassVar[int] = 20_000

    CONSULTA: ClassVar[str] = """
        SELECT "Rip Imóvel", "UF", "Município", "Bairro", "Endereço",
               "Latitude", "Longitude", "Nível de Precisão"
        FROM read_xlsx(?, sheet = ?)
        WHERE "Endereço" IS NOT NULL AND trim("Endereço") <> ''
    """

    def popular(
        self,
        conn: duckdb.DuckDBPyConnection,
    ) -> Iterator[RegistroEtiquetacao]:
        conn.execute("INSTALL excel; LOAD excel;")
        resultado = conn.execute(
            self.CONSULTA, [str(self.arquivo), self.aba or "Sheet1"]
        )

        while True:
            linhas = resultado.fetchmany(self.TAM_LOTE)
            if not linhas:
                break
            for linha in linhas:
                rip, uf, municipio, bairro, endereco, lat, lon, precisao = linha
                yield RegistroEtiquetacao(
                    endereco=str(endereco).strip(),
                    extras=montar_extras(
                        municipio, uf, bairro, banco="Imóveis da União"
                    ),
                    meta={
                        "latitude": converter_float(lat),
                        "longitude": converter_float(lon),
                        "nivel_precisao": precisao,
                        "arquivo": str(self.arquivo),
                        "aba": self.aba or "Sheet1",
                    },
                    origem=self.tipo,
                    origem_id=str(rip),
                )


class PopuladorCensoEscolar(Populador):
    """Escolas do Censo Escolar (INEP): endereço concatenado + geo.

    A origem é o CSV detalhado do censo (uma linha por escola). O endereço já
    vem bruto, com CEP e 'Município - UF' ao fim, e é mantido como veio. O
    contexto da escola (município/UF, nome, dependência e localidade
    diferenciada) entra em `extras`, sem popular segmentos.
    """

    tipo = "censo_escolar"
    rotulo = "Censo Escolar (INEP)"
    TAM_LOTE: ClassVar[int] = 20_000

    # Valores de "Localidade Diferenciada" sem conteúdo útil (não viram extras).
    LOCALIDADE_DIFERENCIADA_IGNORAR: ClassVar[frozenset[str]] = frozenset(
        {
            "A escola não está em área de localização diferenciada",
            "Não Informado",
        }
    )

    CONSULTA: ClassVar[str] = """
        SELECT "Escola", "Código INEP", "UF", "Município",
               "Localidade Diferenciada", "Dependência Administrativa",
               "Endereço", "Latitude", "Longitude"
        FROM read_csv(?, header = true, all_varchar = true)
        WHERE "Endereço" IS NOT NULL AND trim("Endereço") <> ''
    """

    def popular(
        self,
        conn: duckdb.DuckDBPyConnection,
    ) -> Iterator[RegistroEtiquetacao]:
        resultado = conn.execute(self.CONSULTA, [str(self.arquivo)])

        while True:
            linhas = resultado.fetchmany(self.TAM_LOTE)
            if not linhas:
                break
            for linha in linhas:
                (
                    escola,
                    codigo_inep,
                    uf,
                    municipio,
                    localidade,
                    dependencia,
                    endereco,
                    lat,
                    lon,
                ) = linha
                escola = limpar_texto(escola)
                dependencia = limpar_texto(dependencia)
                localidade = self._limpar_localidade(localidade)
                yield RegistroEtiquetacao(
                    endereco=str(endereco).strip(),
                    extras=montar_extras(
                        limpar_texto(municipio),
                        limpar_texto(uf),
                        None,
                        banco="Censo Escolar (INEP)",
                        extras_adicionais=[
                            ("Escola", escola),
                            ("Dependência Administrativa", dependencia),
                            ("Localidade Diferenciada", localidade),
                        ],
                    ),
                    meta={
                        "latitude": converter_float(lat),
                        "longitude": converter_float(lon),
                        "escola": escola,
                        "dependencia_administrativa": dependencia,
                        "localidade_diferenciada": localidade or None,
                        "arquivo": str(self.arquivo),
                    },
                    origem=self.tipo,
                    origem_id=limpar_texto(codigo_inep) or None,
                )

    def _limpar_localidade(self, valor: Any) -> str:
        """Descarta marcadores sem conteúdo útil de localidade diferenciada."""
        texto = limpar_texto(valor)
        if texto.casefold() in {
            ignorar.casefold() for ignorar in self.LOCALIDADE_DIFERENCIADA_IGNORAR
        }:
            return ""
        return texto


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
                )


def _municipios_csv_padrao() -> Path | None:
    """Localiza o `municipios.csv` (cod_ibge, municipio, uf) subindo a partir daqui.

    A ANEEL só traz o código IBGE (`MUN`); este arquivo (em `src/data/` do
    repositório `enderecobr_rs`) resolve o nome do município e a UF.
    """
    for base in Path(__file__).resolve().parents:
        candidato = base / "src" / "data" / "municipios.csv"
        if candidato.is_file():
            return candidato
    return None


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
    ) -> Iterator[RegistroEtiquetacao]:
        municipios = _municipios_csv_padrao()
        if municipios is None:
            raise RuntimeError(
                "municipios.csv (cod_ibge, municipio, uf) não encontrado para "
                "resolver o código IBGE da ANEEL"
            )
        resultado = conn.execute(
            self.CONSULTA, [str(self.arquivo), str(municipios)]
        )

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
                cep = limpar_texto(cep)
                cnae = limpar_texto(cnae)
                situacao = limpar_texto(situacao)
                yield RegistroEtiquetacao(
                    endereco=limpar_texto(lgrd),
                    extras=montar_extras(
                        limpar_texto(municipio),
                        limpar_texto(uf),
                        limpar_texto(brr),
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
                    origem_id=limpar_texto(cod_id)
                    or limpar_texto(pn_con)
                    or None,
                )


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


def _rnd_registro(origem_id: str) -> random.Random:
    """RNG determinístico por entidade (a junção não muda entre execuções).

    `random.Random(str)` semeia via sha512 (independente de PYTHONHASHSEED),
    então a mesma entidade rende sempre a mesma junção.
    """
    return random.Random(origem_id)


def montar_endereco_cneas(
    campos: dict[str, str], nome: str, rnd: random.Random
) -> str:
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
    ) -> Iterator[RegistroEtiquetacao]:
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
                cod_entidade = limpar_texto(cod_entidade)
                razao_social = limpar_texto(razao_social)
                nome_fantasia = limpar_texto(nome_fantasia)
                nome = nome_fantasia or razao_social
                campos = {
                    "logradouro": limpar_texto(logradouro),
                    "numero": limpar_texto(numero),
                    "complemento": limpar_texto(complemento),
                    "bairro": limpar_texto(bairro),
                    "cep": limpar_texto(cep),
                    "municipio": limpar_texto(municipio),
                    "uf": limpar_texto(uf),
                }
                rnd = _rnd_registro(cod_entidade or nome or campos["logradouro"])
                yield RegistroEtiquetacao(
                    endereco=montar_endereco_cneas(campos, nome, rnd),
                    extras=montar_extras(
                        None,
                        None,
                        None,
                        banco="CNEAS (Entidades de Assistência Social)",
                        extras_adicionais=[
                            ("Entidade", nome),
                            ("Situação", limpar_texto(situacao)),
                        ],
                    ),
                    meta={
                        "cod_entidade": cod_entidade,
                        "cnpj": limpar_texto(cnpj) or None,
                        "razao_social": razao_social,
                        "nome_fantasia": nome_fantasia,
                        "municipio": campos["municipio"],
                        "uf": campos["uf"],
                        "cep": campos["cep"] or None,
                        "situacao": limpar_texto(situacao),
                        "arquivo": str(self.arquivo),
                    },
                    origem=self.tipo,
                    origem_id=cod_entidade or None,
                )


POPULADORES: dict[str, type[Populador]] = {
    PopuladorImoveisUniao.tipo: PopuladorImoveisUniao,
    PopuladorCensoEscolar.tipo: PopuladorCensoEscolar,
    PopuladorCafir.tipo: PopuladorCafir,
    PopuladorAneel.tipo: PopuladorAneel,
    PopuladorCneas.tipo: PopuladorCneas,
}


def carregar_populador(tipo: str, arquivo: Path, aba: str | None) -> Populador:
    classe = POPULADORES.get(tipo)
    if classe is None:
        opcoes = ", ".join(sorted(POPULADORES))
        raise typer.BadParameter(
            f"tipo_dataset desconhecido: {tipo!r}. Opções: {opcoes}."
        )
    return classe(arquivo, aba)


# --- Destino SQLite -------------------------------------------------------


def calcular_hash(endereco: str) -> str:
    return hashlib.sha256(endereco.encode("utf-8")).hexdigest()


def criar_banco(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS enderecos (
            id INTEGER PRIMARY KEY,
            endereco TEXT NOT NULL,
            extras TEXT NOT NULL DEFAULT '',
            meta TEXT NOT NULL DEFAULT '{}',
            resposta_llm TEXT,
            origem TEXT NOT NULL,
            origem_id TEXT,
            lote TEXT NOT NULL,
            hash_endereco TEXT NOT NULL UNIQUE,
            data_criacao TEXT NOT NULL,
            data_processamento TEXT,
            llm TEXT
        );
        """
    )


def contar_registros(conn: sqlite3.Connection) -> int:
    linha = conn.execute("SELECT count(*) FROM enderecos").fetchone()
    return int(linha[0])


def ler_enderecos_existentes(conn: sqlite3.Connection) -> list[str]:
    return [linha[0] for linha in conn.execute("SELECT endereco FROM enderecos")]


def gravar_registros(
    conn: sqlite3.Connection,
    registros: Iterable[RegistroEtiquetacao],
    lote: str,
) -> tuple[int, int]:
    """Insere ignorando hashes já presentes. Retorna (inseridos, ignorados)."""
    agora = datetime.now(UTC).isoformat()
    # `id` é a unix epoch em nanossegundos (offset por índice evita colisão
    # quando duas linhas caem no mesmo nanossegundo).
    base_ns = time.time_ns()
    antes = conn.total_changes
    total = 0
    for i, r in enumerate(registros):
        conn.execute(
            """
            INSERT OR IGNORE INTO enderecos
                (id, endereco, extras, meta, origem, origem_id, lote,
                 hash_endereco, data_criacao)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                base_ns + i,
                r.endereco,
                r.extras,
                json.dumps(r.meta, ensure_ascii=False),
                r.origem,
                r.origem_id,
                lote,
                calcular_hash(r.endereco),
                agora,
            ),
        )
        total += 1
    conn.commit()
    inseridos = conn.total_changes - antes
    return inseridos, total - inseridos


def montar_lote(tipo_dataset: str) -> str:
    return f"{tipo_dataset}-{datetime.now(UTC):%Y%m%dT%H%M%S}"


# --- Amostragem -----------------------------------------------------------


@dataclass
class ResultadoAmostragem:
    amostra: list[RegistroEtiquetacao]
    candidatos: int
    aceitos: int


def reservatorio(
    fonte: Iterator[RegistroEtiquetacao],
    tamanho: int,
    seed: int | None,
) -> list[RegistroEtiquetacao]:
    """Reservoir sampling (Algoritmo R): amostra uniforme de `tamanho`.

    Um único passe e memória constante (`tamanho` registros), independente do
    tamanho da origem.
    """
    rnd = random.Random(seed)
    reserva: list[RegistroEtiquetacao] = []

    for i, registro in enumerate(fonte):
        if i < tamanho:
            reserva.append(registro)
        else:
            # Troca com probabilidade tamanho / (i + 1).
            escolhido = rnd.randrange(i + 1)
            if escolhido < tamanho:
                reserva[escolhido] = registro

    return reserva


def amostrar_diverso(
    populador: Populador,
    criar_filtro: Callable[[], FiltroDiversidade],
    *,
    tamanho: int,
    seed: int | None,
    fator_inicial: int = 3,
    max_rodadas: int = 2,
) -> ResultadoAmostragem:
    """Amostra `tamanho` endereços diversos, repetindo até atingir o pedido.

    Cada rodada faz um reservoir de `tamanho * fator` candidatos (uma leitura
    da origem) e aplica o filtro de diversidade sobre esse pool, **parando
    assim que `tamanho` forem aceitos**. O pool é limitado de propósito (o
    filtro fuzzy custa O(aceitos) por candidato, então passar o filtro na
    origem inteira seria inviável) e só é ampliado (dobrado) quando o pool
    inteiro não bastou para atingir o pedido.

    O pool é embaralhado antes do filtro: o reservoir mantém os `tamanho`
    primeiros na ordem da origem, então parar cedo nesse prefixo enviesaria a
    amostra pela posição no arquivo (na ANEEL/parquet, clusterização
    geográfica).
    """
    fator = fator_inicial
    candidatos = 0
    aceitos = 0
    amostra: list[RegistroEtiquetacao] = []
    rnd = random.Random(seed)

    for _ in range(max_rodadas):
        conn = duckdb.connect()
        try:
            pool = reservatorio(populador.popular(conn), tamanho * fator, seed)
        finally:
            conn.close()

        rnd.shuffle(pool)
        filtro = criar_filtro()
        examinados = 0
        amostra = []
        for registro in tqdm.tqdm(pool, total=len(pool)):
            examinados += 1
            if filtro.aceitar(registro.endereco):
                amostra.append(registro)
                if len(amostra) >= tamanho:
                    break
        candidatos, aceitos = examinados, len(amostra)

        if aceitos >= tamanho:
            break
        fator *= 2

    return ResultadoAmostragem(amostra[:tamanho], candidatos, aceitos)


# --- CLI ------------------------------------------------------------------

app = typer.Typer(no_args_is_help=True, add_completion=False)


@app.command()
def popular(
    tipo_dataset: Annotated[
        str, typer.Argument(help="Chave do populador (ex.: imoveis_uniao).")
    ],
    arquivo: Annotated[Path, typer.Argument(help="Arquivo de origem.")],
    destino: Annotated[
        Path, typer.Argument(help="SQLite de destino (append se já existir).")
    ],
    tamanho_amostra: Annotated[
        int,
        typer.Option(
            "--tamanho-amostra", "-n", min=1, help="Qtd. de endereços sorteados."
        ),
    ] = 1000,
    seed: Annotated[
        int | None,
        typer.Option("--seed", help="Semente do sorteio (reprodutibilidade)."),
    ] = None,
    similaridade_maxima: Annotated[
        float | None,
        typer.Option(
            "--similaridade-maxima",
            help="Descarta sorteados com similaridade >= X (0–100, rapidfuzz).",
        ),
    ] = None,
    aba: Annotated[
        str | None, typer.Option("--aba", help="Aba da planilha (xlsx).")
    ] = None,
) -> None:
    """Sorteia endereços de uma origem e popula o dataset de etiquetagem."""
    if not arquivo.is_file():
        raise typer.BadParameter(f"Arquivo de origem não encontrado: {arquivo}")

    populador = carregar_populador(tipo_dataset, arquivo, aba)
    lote = montar_lote(tipo_dataset)

    destino.parent.mkdir(parents=True, exist_ok=True)
    conn_destino = sqlite3.connect(str(destino))
    try:
        criar_banco(conn_destino)

        existentes = (
            ler_enderecos_existentes(conn_destino)
            if similaridade_maxima is not None
            else []
        )

        def criar_filtro() -> FiltroDiversidade:
            if similaridade_maxima is None:
                return SemFiltroDiversidade()
            return FiltroDiversidadeFuzzy(
                existentes, similaridade_maxima=similaridade_maxima
            )

        if similaridade_maxima is not None:
            console.print(
                f"[dim]Filtro fuzzy comparando com {len(existentes)} "
                "endereços já no banco.[/dim]"
            )
        console.print(
            f"[bold]{populador.rotulo}[/bold] — lendo a origem e "
            f"amostrando até {tamanho_amostra} endereços…"
        )

        resultado = amostrar_diverso(
            populador,
            criar_filtro,
            tamanho=tamanho_amostra,
            seed=seed,
            # Sem filtro não há descarte: o pool já é o tamanho final.
            fator_inicial=1 if similaridade_maxima is None else 3,
        )

        inseridos, ignorados = gravar_registros(conn_destino, resultado.amostra, lote)
        total = contar_registros(conn_destino)
    finally:
        conn_destino.close()

    descartados = resultado.candidatos - resultado.aceitos
    console.rule("Resumo")
    console.print(f"Lote: [bold]{lote}[/bold]")
    console.print(f"Candidatos avaliados: {resultado.candidatos}")
    if descartados:
        console.print(f"Descartados por diversidade: [yellow]{descartados}[/yellow]")
    console.print(
        f"Tamanho da amostra: [bold]{len(resultado.amostra)}[/bold] / {tamanho_amostra}"
    )
    console.print(f"Inseridos: [green]{inseridos}[/green]")
    console.print(f"Ignorados (hash duplicado): {ignorados}")
    console.print(f"Total no banco: [bold]{total}[/bold]")


if __name__ == "__main__":
    app()
