"""Bases publicas que alimentam o dataset."""

from __future__ import annotations

from pathlib import Path

import typer

from crf_endereco.anotacao.populacao.aneel import PopuladorAneel
from crf_endereco.anotacao.populacao.cadunico import (
    PopuladorCadUnico,
    formatar_cep,
    montar_endereco_cadunico,
    normalizar_localidade,
    normalizar_numero,
)
from crf_endereco.anotacao.populacao.cafir import PopuladorCafir
from crf_endereco.anotacao.populacao.censo_escolar import PopuladorCensoEscolar
from crf_endereco.anotacao.populacao.cneas import PopuladorCneas
from crf_endereco.anotacao.populacao.imoveis_uniao import PopuladorImoveisUniao
from crf_endereco.anotacao.populacao.populador import Populador
from crf_endereco.anotacao.populacao.siase import PopuladorSiase

POPULADORES: dict[str, type[Populador]] = {
    PopuladorImoveisUniao.tipo: PopuladorImoveisUniao,
    PopuladorCensoEscolar.tipo: PopuladorCensoEscolar,
    PopuladorCafir.tipo: PopuladorCafir,
    PopuladorAneel.tipo: PopuladorAneel,
    PopuladorCneas.tipo: PopuladorCneas,
    PopuladorSiase.tipo: PopuladorSiase,
    PopuladorCadUnico.tipo: PopuladorCadUnico,
}


def carregar_populador(tipo: str, arquivo: Path, aba: str | None) -> Populador:
    classe = POPULADORES.get(tipo)
    if classe is None:
        opcoes = ", ".join(sorted(POPULADORES))
        raise typer.BadParameter(
            f"tipo_dataset desconhecido: {tipo!r}. Opções: {opcoes}."
        )
    return classe(arquivo, aba)


__all__ = [
    "POPULADORES",
    "Populador",
    "PopuladorAneel",
    "PopuladorCadUnico",
    "PopuladorCafir",
    "PopuladorCensoEscolar",
    "PopuladorCneas",
    "PopuladorImoveisUniao",
    "PopuladorSiase",
    "carregar_populador",
    "formatar_cep",
    "montar_endereco_cadunico",
    "normalizar_localidade",
    "normalizar_numero",
]
