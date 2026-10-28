"""Bases publicas que alimentam o dataset (uma por arquivo)."""

from __future__ import annotations

import typer

from crf_endereco.anotacao.populacao.aneel import FONTE as FONTE_ANEEL
from crf_endereco.anotacao.populacao.cadunico import FONTE as FONTE_CADUNICO
from crf_endereco.anotacao.populacao.cadunico import (
    formatar_cep,
    normalizar_localidade,
    normalizar_numero,
)
from crf_endereco.anotacao.populacao.cadunico import (
    montar_endereco as montar_endereco_cadunico,
)
from crf_endereco.anotacao.populacao.cafir import FONTE as FONTE_CAFIR
from crf_endereco.anotacao.populacao.censo_escolar import FONTE as FONTE_CENSO_ESCOLAR
from crf_endereco.anotacao.populacao.cneas import FONTE as FONTE_CNEAS
from crf_endereco.anotacao.populacao.imoveis_uniao import FONTE as FONTE_IMOVEIS_UNIAO
from crf_endereco.anotacao.populacao.populador import Fonte
from crf_endereco.anotacao.populacao.siase import FONTE as FONTE_SIASE

FONTES: dict[str, Fonte] = {
    fonte.tipo: fonte
    for fonte in (
        FONTE_ANEEL,
        FONTE_CADUNICO,
        FONTE_CAFIR,
        FONTE_CENSO_ESCOLAR,
        FONTE_CNEAS,
        FONTE_IMOVEIS_UNIAO,
        FONTE_SIASE,
    )
}


def carregar_fonte(tipo: str) -> Fonte:
    """A base pedida na linha de comando (erro claro quando nao existe)."""
    fonte = FONTES.get(tipo)
    if fonte is None:
        raise typer.BadParameter(
            f"tipo_dataset desconhecido: {tipo!r}. Opções: {', '.join(sorted(FONTES))}."
        )
    return fonte


__all__ = [
    "FONTES",
    "Fonte",
    "carregar_fonte",
    "formatar_cep",
    "montar_endereco_cadunico",
    "normalizar_localidade",
    "normalizar_numero",
]
