"""Linha de comando do pipeline de CRF de enderecos."""

from __future__ import annotations

import typer

from crf_endereco.cli import geocode, modelo, producao

app = typer.Typer(
    no_args_is_help=True,
    add_completion=False,
    help="Popula, anota, treina e avalia o segmentador de enderecos.",
)

app.add_typer(producao.app, name="etiquetar", help="Etiqueta enderecos com uma LLM.")
app.add_typer(
    geocode.app, name="geocode", help="Compara o geocode bruto e o segmentado."
)
for comando in (
    producao.popular,
    modelo.treinar,
    modelo.tunar,
    modelo.avaliar,
    modelo.segmentar,
    modelo.diferencial,
    modelo.inspecionar,
):
    app.command(help=comando.__doc__)(comando)
