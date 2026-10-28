"""Comparacao entre geocodificar o endereco bruto e o segmentado."""

from __future__ import annotations

import re
import time
import warnings
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import cast

import duckdb
import pandas as pd
import pyarrow as pa
import typer

CAMPOS_ENDERECO = (
    "estado",
    "municipio",
    "logradouro",
    "numero",
    "complemento",
    "cep",
    "localidade",
)

# campos que o geocodebr aceita
CAMPOS_GEOCODEBR = ("estado", "municipio", "logradouro", "numero", "cep", "localidade")

# campos da base que entram no texto a segmentar
CAMPOS_TEXTO = ("logradouro", "numero", "complemento", "localidade")

COLUNAS_RESERVADAS = {"id", "endereco", *CAMPOS_ENDERECO}

PADRAO_IDENTIFICADOR = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# precisao do geocodebr, da mais para a menos precisa
ORDEM_PRECISAO = (
    "numero",
    "numero_aproximado",
    "logradouro",
    "cep",
    "localidade",
    "municipio",
)

# mesma ordem da tabela do artigo do geocodebr: agrupado por precisao e, dentro
# do grupo, deterministico (d) antes do probabilistico (p)
# https://ipea.github.io/geocodebr/articles/geocode.html
ORDEM_TIPO_RESULTADO = (
    "dn01",
    "dn02",
    "dn03",
    "dn04",
    "pn01",
    "pn02",
    "pn03",
    "pn04",
    "da01",
    "da02",
    "da03",
    "da04",
    "pa01",
    "pa02",
    "pa03",
    "pa04",
    "dl01",
    "dl02",
    "dl03",
    "dl04",
    "pl01",
    "pl02",
    "pl03",
    "pl04",
    "dc01",
    "dc02",
    "db01",
    "dm01",
)

SEM_RESULTADO = "(nao encontrado)"

# numero pode vir como double (ex.: exportado do R) e o cast viraria "315.0",
# que o geocodebr nao reconhece como numero
SQL_NUMERO = "nullif(trim(regexp_replace(cast({} as varchar), '[.]0+$', '')), '')"

SQL_EXTRAIDO = "nullif(trim({}), '')"

SQL_GEOCODE = """
create or replace view geocode as
select 'bruto' as versao, precisao, tipo_resultado from bruto
union all
select 'processado' as versao, precisao, tipo_resultado from processado
"""

# `delta_pp` sai depois, no pandas: diferenca de frequencia entre as versoes
SQL_COMPARAR = """
with contagem as (
    select versao,
           coalesce({coluna}, '{sem}') as categoria,
           count(*) as n
    from geocode
    group by versao, categoria
),
frequencia as (
    select versao, categoria, n,
           cast(100.0 * n / sum(n) over (partition by versao) as double) as pct
    from contagem
)
select categoria,
       cast(coalesce(sum(n) filter (where versao = 'bruto'), 0) as bigint) as n_bruto,
       cast(coalesce(sum(pct) filter (where versao = 'bruto'), 0) as double) as prop_bruto,
       cast(coalesce(sum(n) filter (where versao = 'processado'), 0) as bigint) as n_estruturado,
       cast(coalesce(sum(pct) filter (where versao = 'processado'), 0) as double) as prop_estruturado
from frequencia
group by categoria
"""


@contextmanager
def cronometrar(rotulo: str, silencioso: bool = False) -> Generator[None]:
    """Imprime o tempo gasto por uma etapa."""
    inicio = time.perf_counter()
    if not silencioso:
        print(f"[{rotulo}] ...", flush=True)
    yield
    if not silencioso:
        print(f"[{rotulo}] {time.perf_counter() - inicio:.1f}s", flush=True)


def identificador(nome: str) -> str:
    if not PADRAO_IDENTIFICADOR.match(nome):
        raise typer.BadParameter(f"nome de coluna invalido: {nome!r}")
    return f'"{nome}"'


def texto(coluna: str) -> str:
    return f"nullif(trim(cast({identificador(coluna)} as varchar)), '')"


def texto_numero(coluna: str) -> str:
    return SQL_NUMERO.format(identificador(coluna))


def resolver_entrada(base: Path) -> str:
    """Aceita um parquet, um diretorio de parquets ou um glob."""
    return str(base / "*.parquet") if base.is_dir() else str(base)


def ler_colunas(con: duckdb.DuckDBPyConnection, caminho: str) -> list[str]:
    return con.read_parquet(caminho).columns


def validar_campos(
    colunas: list[str], campos: dict[str, str | None], chave: str | None
) -> None:
    for campo, coluna in campos.items():
        if coluna is not None and coluna not in colunas:
            raise typer.BadParameter(f"coluna de {campo} ausente na base: {coluna!r}")
    for campo in ("estado", "municipio"):
        if campos[campo] is None:
            raise typer.BadParameter("--estado e --municipio sao obrigatorios")
    if chave is not None and (chave not in colunas or chave in COLUNAS_RESERVADAS):
        raise typer.BadParameter(f"--chave ausente na base ou reservada: {chave!r}")


def montar_estagio(
    con: duckdb.DuckDBPyConnection,
    entrada: str,
    destino: Path,
    campos: dict[str, str | None],
    endereco: str | None,
    chave: str | None,
    limite: int,
) -> None:
    """Parquet de trabalho: id interno + campos mapeados + texto a segmentar."""
    selecao = ["row_number() over () - 1 as id"]
    if chave is not None:
        selecao.append(f"{identificador(chave)} as chave")
    for campo in CAMPOS_ENDERECO:
        coluna = campos[campo]
        if coluna is None:
            selecao.append(f"null::varchar as {campo}")
        elif campo == "numero":
            selecao.append(f"{texto_numero(coluna)} as numero")
        else:
            selecao.append(f"{texto(coluna)} as {campo}")

    if endereco is not None:
        partes = [texto(endereco)]
    else:
        origens = [campos[c] for c in CAMPOS_TEXTO]
        partes = [texto(coluna) for coluna in origens if coluna is not None]
    if not partes:
        raise typer.BadParameter("nenhuma coluna de texto para segmentar")
    selecao.append(f"nullif(trim(concat_ws(' ', {', '.join(partes)})), '') as endereco")

    relacao = con.read_parquet(entrada)
    if limite > 0:
        relacao = relacao.limit(limite)
    relacao.project(", ".join(selecao)).write_parquet(str(destino), compression="zstd")


# campos que a base sempre traz prontos: o CRF nao extrai nenhum dos dois
CAMPOS_FIXOS = ("estado", "municipio")


def montar_entradas(
    con: duckdb.DuckDBPyConnection,
    estagio: Path,
    segmentado: Path,
    pasta: Path,
    campos: dict[str, str | None],
    chave: str | None,
) -> dict[str, Path]:
    """Entradas do geocodebr: so a base e a base mais a extracao do CRF.

    Em `processado` a extração vence sempre que encontra algo, mesmo em campo
    que a base ja tinha: o valor estruturado pode vir sujo (o logradouro da
    RAIS e o endereço inteiro) e quem mede a melhoria e a extração. So
    estado e município ficam intocados.
    """
    identificacao = ["id"] + (["chave"] if chave is not None else [])
    estruturados = [c for c in CAMPOS_GEOCODEBR if campos[c] is not None]

    bruto = pasta / "bruto_entrada.parquet"
    colunas_bruto = ", ".join([*identificacao, *estruturados])
    con.read_parquet(str(estagio)).project(colunas_bruto).write_parquet(
        str(bruto), compression="zstd"
    )

    # no join as duas relacoes tem `id`: tudo sai com alias
    selecao = [f"s.{c} as {c}" for c in identificacao]
    for campo in CAMPOS_GEOCODEBR:
        if campo in CAMPOS_FIXOS:
            selecao.append(f"s.{campo} as {campo}")
        else:
            extraido = SQL_EXTRAIDO.format(f"g.{campo}_extraido")
            selecao.append(f"coalesce({extraido}, s.{campo}) as {campo}")

    processado = pasta / "processado_entrada.parquet"
    (
        con.read_parquet(str(estagio))
        .set_alias("s")
        .join(
            con.read_parquet(str(segmentado)).set_alias("g"), "s.id = g.id", how="left"
        )
        .project(", ".join(selecao))
        .write_parquet(str(processado), compression="zstd")
    )
    return {"bruto": bruto, "processado": processado}


# o geocodebr materializa no DuckDB o CNEFE inteiro dos municipios presentes na
# entrada (~10 GB no Brasil todo): fatiar por municipios mantem a memoria
# proporcional ao lote, e nao ao pais
MUNICIPIOS_POR_LOTE = 200

SQL_LOTES = """
create or replace temp table lotes as
select estado, municipio,
       (row_number() over (order by estado, municipio) - 1) // ? as lote
from municipios_base
"""


def contar(con: duckdb.DuckDBPyConnection, consulta: str) -> int:
    """Devolve a primeira coluna da primeira linha de uma consulta."""
    linha = con.sql(consulta).fetchone()
    return 0 if linha is None or linha[0] is None else int(linha[0])


def geocodificar(
    con: duckdb.DuckDBPyConnection,
    entrada: Path,
    destino: Path,
    n_cores: int,
    silencioso: bool = False,
) -> int:
    """Geocodifica o parquet por lotes de municípios, com todos os campos dele."""
    import geocodebr

    colunas = set(ler_colunas(con, str(entrada)))
    campos_endereco: dict[str, str | None] = {
        c: c for c in CAMPOS_GEOCODEBR if c in colunas
    }

    _ = (
        con.read_parquet(str(entrada))
        .project("estado, municipio")
        .distinct()
        .to_view("municipios_base")
    )
    _ = con.sql(SQL_LOTES, params=[MUNICIPIOS_POR_LOTE])
    n_lotes = contar(con, "select max(lote) + 1 from lotes")

    pasta = entrada.parent / "lotes"
    pasta.mkdir(exist_ok=True)
    trechos: list[str] = []
    linhas = 0
    for lote in range(n_lotes):
        trecho = pasta / f"entrada_{lote}.parquet"
        resultado = pasta / f"resultado_{lote}.parquet"
        municipios = con.sql(
            "select estado, municipio from lotes where lote = ?", params=[lote]
        ).set_alias("m")
        condicao = "e.estado = m.estado and e.municipio = m.municipio"
        _ = (
            con.read_parquet(str(entrada))
            .set_alias("e")
            .join(municipios, condicao, how="semi")
            .write_parquet(str(trecho), compression="zstd")
        )
        if not silencioso:
            print(f"[geocode lote {lote + 1}/{n_lotes}] {trecho.name}", flush=True)
        with warnings.catch_warnings():
            if silencioso:
                warnings.simplefilter("ignore")
            tabela = cast(
                pa.Table,
                geocodebr.geocode(
                    trecho,
                    campos_endereco=campos_endereco,
                    n_cores=n_cores if n_cores > 0 else None,
                    verboso=not silencioso,
                ),
            )
        _ = con.register("resultado_geocode", tabela)
        _ = con.table("resultado_geocode").write_parquet(
            str(resultado), compression="zstd"
        )
        _ = con.unregister("resultado_geocode")
        linhas += tabela.num_rows
        trechos.append(str(resultado))
        del tabela

    _ = con.read_parquet(trechos).write_parquet(str(destino), compression="zstd")
    return linhas


def registrar_visoes(
    con: duckdb.DuckDBPyConnection, bruto: Path, processado: Path
) -> None:
    for versao, arquivo in (("bruto", bruto), ("processado", processado)):
        colunas = "precisao, tipo_resultado"
        _ = con.read_parquet(str(arquivo)).project(colunas).to_view(versao)
    _ = con.sql(SQL_GEOCODE)


def imprime(titulo: str, df: pd.DataFrame) -> None:
    print(f"\n{titulo}\n{'=' * len(titulo)}")
    print(df.to_string(index=False, float_format="{:,.2f}".format))


def _comparar(
    con: duckdb.DuckDBPyConnection, coluna: str, ordem: tuple[str, ...]
) -> pd.DataFrame:
    """Frequência de cada categoria nas duas versões, na ordem recebida."""
    df = con.sql(SQL_COMPARAR.format(coluna=coluna, sem=SEM_RESULTADO)).df()
    df["delta"] = df["prop_estruturado"] - df["prop_bruto"]
    categorias = [str(c) for c in df["categoria"]]
    # categoria fora da ordem conhecida vai para o fim, antes de `sem resultado`
    posicao = {c: i for i, c in enumerate(ordem)}
    posicao[SEM_RESULTADO] = len(ordem) + 1
    df["_posicao"] = [posicao.get(c, len(ordem)) for c in categorias]
    return df.sort_values("_posicao").drop(columns="_posicao").reset_index(drop=True)


def relatar(con: duckdb.DuckDBPyConnection) -> None:
    """Imprime a precisão e o tipo de resultado das duas versoes."""
    imprime("Precisao", _comparar(con, "precisao", ORDEM_PRECISAO))
    imprime("Tipo de resultado", _comparar(con, "tipo_resultado", ORDEM_TIPO_RESULTADO))
