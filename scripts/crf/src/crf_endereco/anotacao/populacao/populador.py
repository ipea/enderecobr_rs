"""Contrato dos populadores e utilidades comuns."""

from __future__ import annotations

import random
from abc import ABC, abstractmethod
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar

import duckdb
from rapidfuzz import fuzz, process
from rich.console import Console

console = Console()

console = Console()

@dataclass
class RegistroEtiquetacao:
    """Uma linha do dataset a etiquetar, antes de virar registro no SQLite.

    `municipio`/`uf` são o contexto administrativo da linha (vêm da origem);
    vão normalizados nas colunas homônimas do banco, sem alterar `extras`/`meta`.
    """

    endereco: str
    extras: str
    meta: dict[str, Any]
    origem: str
    origem_id: str | None = None
    municipio: str | None = None
    uf: str | None = None

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

def normalizar_municipio(valor: Any) -> str | None:
    """Nome do município em maiúsculas (None quando vazio)."""
    return limpar_texto(valor).upper() or None

def normalizar_uf(valor: Any) -> str | None:
    """Sigla da UF em maiúsculas (None quando vazia)."""
    return limpar_texto(valor).upper() or None

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

def _ultimo_campo(endereco: str) -> str:
    """Último campo do endereço (após a última vírgula) — candidato a bairro.

    Vazio quando o endereço não tem vírgula (linha de campo único).
    """
    partes = [parte.strip() for parte in endereco.split(",")]
    if len(partes) < 2:
        return ""
    return partes[-1]

def _limpar_cep(valor: Any) -> str:
    """CEP como texto; `None` e o código `0` (ausentes) viram ''."""
    texto = limpar_texto(valor)
    return "" if texto in ("", "0") else texto

def _rnd_registro(origem_id: str) -> random.Random:
    """RNG determinístico por entidade (a junção não muda entre execuções).

    `random.Random(str)` semeia via sha512 (independente de PYTHONHASHSEED),
    então a mesma entidade rende sempre a mesma junção.
    """
    return random.Random(origem_id)


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
