"""Registro a etiquetar e a normalizacao dos campos vindos das bases."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any


@dataclass
class Registro:
    """Uma linha do dataset a etiquetar (antes de virar registro no SQLite).

    `municipio`/`uf` sao o contexto administrativo da linha (vem da origem) e
    vao normalizados nas colunas homonimas do banco, sem alterar `extras`/`meta`.
    Use `registro()` para construi-lo: e la que a normalizacao acontece.
    """

    endereco: str
    extras: str
    meta: dict[str, Any]
    origem: str
    origem_id: str | None = None
    municipio: str | None = None
    uf: str | None = None


def registro(
    *,
    endereco: Any,
    extras: str,
    meta: dict[str, Any],
    origem: str,
    origem_id: Any = None,
    municipio: Any = None,
    uf: Any = None,
) -> Registro:
    """Monta um `Registro` normalizando endereco, identificador, municipio e UF."""
    return Registro(
        endereco=texto(endereco),
        extras=extras,
        meta=meta,
        origem=origem,
        origem_id=texto(origem_id) or None,
        municipio=maiusculo(municipio),
        uf=maiusculo(uf),
    )


def texto(valor: Any) -> str:
    """Valor textual sem espacos nas pontas (None vira '')."""
    return "" if valor is None else str(valor).strip()


def maiusculo(valor: Any) -> str | None:
    """Texto em maiusculas (None quando vazio)."""
    return texto(valor).upper() or None


def numero(valor: Any) -> str:
    """Numero do logradouro sem os zeros a esquerda.

    O cadastro grava o numero zero-padded (`000…22`); numero ausente (`0`,
    `000…0` ou vazio) devolve ''. Valores nao numericos (ex.: `S/N`) ficam
    como vieram.
    """
    bruto = texto(valor)
    return bruto.lstrip("0") if bruto.isdigit() else bruto


def cep(valor: Any) -> str:
    """CEP como texto; `None` e o codigo `0` (ausentes) viram ''."""
    bruto = texto(valor)
    return "" if bruto in {"", "0"} else bruto


def decimal(valor: Any) -> float | None:
    """Converte numeros com virgula decimal (ex.: '-8,0962257') em float."""
    if valor is None:
        return None
    try:
        return float(str(valor).replace(",", "."))
    except ValueError:
        return None


def montar_extras(
    municipio: str | None,
    uf: str | None,
    bairro: str | None,
    *,
    banco: str,
    extras_adicionais: Iterable[tuple[str, str]] = (),
) -> str:
    """Monta a 'extra info' (contexto; nao popula segmentos).

    `extras_adicionais` sao pares (rotulo, valor) especificos de cada origem,
    gravados entre o bairro e o banco; valores vazios sao omitidos.
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
