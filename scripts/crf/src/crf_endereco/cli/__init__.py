"""Linha de comando do pipeline de CRF de enderecos."""

from __future__ import annotations

import typer

from crf_endereco.cli import (
    avaliar,
    comparar_geocode,
    diferencial,
    etiquetar,
    inspecionar,
    popular,
    segmentar,
    treinar,
    tunar,
)

app = typer.Typer(
    no_args_is_help=True,
    add_completion=False,
    help="Popula, anota, treina e avalia o segmentador de enderecos.",
)

app.command(name="popular", help="Popula o dataset com bases publicas.")(
    popular.popular
)
app.add_typer(etiquetar.app, name="etiquetar", help="Etiqueta enderecos com uma LLM.")
app.command(name="treinar", help="Treina o CRF.")(treinar.treinar)
app.command(name="tunar", help="Busca hiperparametros do CRF.")(tunar.tunar)
app.command(name="avaliar", help="Avalia o CRF por token e classe.")(avaliar.avaliar)
app.command(name="segmentar", help="Segmenta enderecos lidos do stdin.")(
    segmentar.segmentar
)
app.command(name="diferencial", help="Compara a segmentacao Python e Rust.")(
    diferencial.diferencial
)
app.command(name="inspecionar", help="Inspeciona os pesos do CRF.")(
    inspecionar.inspecionar
)
app.command(
    name="comparar-geocode",
    help="Compara o geocode do endereco bruto e do segmentado.",
)(comparar_geocode.comparar_geocode)
