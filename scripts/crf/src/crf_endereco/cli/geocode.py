"""Comando que compara o geocode bruto e o segmentado."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Annotated

import duckdb
import typer

from crf_endereco.geocode import comparacao
from crf_endereco.geocode.comparacao import relatar
from crf_endereco.segmentador_rust import BINARIO_LOTE, segmentar_lote

app = typer.Typer(no_args_is_help=True, add_completion=False)


@app.command(name="comparar")
def comparar(
    base: Annotated[
        Path, typer.Argument(help="parquet (ou diretorio/glob) de entrada")
    ],
    estado: Annotated[str, typer.Option(help="coluna do estado (UF ou nome)")],
    municipio: Annotated[
        str, typer.Option(help="coluna do municipio (nome ou codigo IBGE)")
    ],
    logradouro: Annotated[str | None, typer.Option(help="coluna do logradouro")] = None,
    numero: Annotated[str | None, typer.Option(help="coluna do numero")] = None,
    complemento: Annotated[
        str | None, typer.Option(help="coluna do complemento")
    ] = None,
    cep: Annotated[str | None, typer.Option(help="coluna do CEP")] = None,
    localidade: Annotated[
        str | None, typer.Option(help="coluna da localidade/bairro")
    ] = None,
    endereco: Annotated[
        str | None,
        typer.Option(
            help="coluna com o endereco completo a segmentar (padrao: compor dos campos)"
        ),
    ] = None,
    chave: Annotated[
        str | None, typer.Option(help="coluna de identificacao preservada nas saidas")
    ] = None,
    limite: Annotated[
        int, typer.Option(help="processa apenas os N primeiros registros (0 = todos)")
    ] = 0,
    saida: Annotated[
        Path | None, typer.Option(help="diretorio das saidas (padrao: o da base)")
    ] = None,
    binario: Annotated[
        Path, typer.Option(help="caminho do binario padronizacao-lote")
    ] = BINARIO_LOTE,
    n_cores: Annotated[int, typer.Option(help="cores usados (0 = todos)")] = 0,
    reusar: Annotated[
        bool, typer.Option(help="reaproveita segmentacao e geocodificacoes ja feitas")
    ] = False,
) -> None:
    """Compara o geocode do endereco bruto com o do endereco segmentado."""
    if not base.exists():
        raise typer.BadParameter(f"base nao encontrada: {base}")
    entrada = comparacao.resolver_entrada(base)
    pasta_saida = (saida or base.parent).resolve()
    pasta_saida.mkdir(parents=True, exist_ok=True)
    raiz = base.stem if base.is_file() else base.name
    segmentado = pasta_saida / f"{raiz}_segmentado.parquet"
    destinos = {
        "bruto": pasta_saida / f"{raiz}_bruto.parquet",
        "processado": pasta_saida / f"{raiz}_processado.parquet",
    }

    con = duckdb.connect()
    campos: dict[str, str | None] = {
        "estado": estado,
        "municipio": municipio,
        "logradouro": logradouro,
        "numero": numero,
        "complemento": complemento,
        "cep": cep,
        "localidade": localidade,
    }
    comparacao.validar_campos(comparacao.ler_colunas(con, entrada), campos, chave)

    print(f"base: {entrada}\nsaida: {pasta_saida}\nsegmentador: {binario}")
    print(
        "campos: " + ", ".join(f"{k}={v}" for k, v in campos.items() if v is not None)
    )
    if endereco is not None:
        print(f"texto segmentado: coluna {endereco!r}")
    else:
        print("texto segmentado: logradouro + numero + complemento + localidade")

    temporaria = tempfile.TemporaryDirectory(dir=pasta_saida, prefix=".tmp_")
    estagio = Path(temporaria.name) / "estagio.parquet"
    try:
        with comparacao.cronometrar("estagio"):
            comparacao.montar_estagio(
                con, entrada, estagio, campos, endereco, chave, limite
            )

        if reusar and segmentado.exists():
            print(f"segmentacao reutilizada: {segmentado}")
        else:
            with comparacao.cronometrar("segmentacao"):
                segmentar_lote(binario, estagio, segmentado, n_cores, chave is not None)

        entradas = comparacao.montar_entradas(
            con, estagio, segmentado, Path(temporaria.name), campos, chave
        )
        for versao, arquivo in entradas.items():
            destino = destinos[versao]
            if reusar and destino.exists():
                print(f"{versao}: reutilizado -> {destino}")
                continue
            with comparacao.cronometrar(f"geocode {versao}"):
                linhas = comparacao.geocodificar(con, arquivo, destino, campos, n_cores)
            print(f"{versao}: {linhas:,} linhas -> {destino}".replace(",", "."))

        for destino in destinos.values():
            if not destino.exists():
                raise typer.BadParameter(f"saida ausente: {destino}")

        comparacao.registrar_visoes(
            con, estagio, segmentado, destinos["bruto"], destinos["processado"]
        )
        relatar(con, campos)
    finally:
        temporaria.cleanup()
