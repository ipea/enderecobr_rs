"""Comparacao entre geocodificar o endereco bruto e o segmentado."""

from __future__ import annotations

import re
import time
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

CAMPOS_EXTRAIVEIS = ("logradouro", "numero", "complemento", "localidade", "cep")

CAMPOS_GEOCODEBR = ("estado", "municipio", "logradouro", "numero", "cep", "localidade")

COLUNAS_RESERVADAS = {"id", "endereco", *CAMPOS_ENDERECO}

PADRAO_IDENTIFICADOR = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# numero pode vir como double (ex.: exportado do R) e o cast viraria "315.0",
# que o geocodebr nao reconhece como numero
SQL_NUMERO = "nullif(trim(regexp_replace(cast({} as varchar), '[.]0+$', '')), '')"

SQL_EXTRAIDO = "nullif(trim({}), '')"

SQL_GEOCODE = """
create or replace view geocode as
select 'bruto' as versao, * from bruto
union all
select 'processado' as versao, * from processado
"""

SQL_PAR = """
create or replace view par as
select b.id,
       b.lat as lat_bruto, b.lon as lon_bruto,
       b.precisao as precisao_bruto, b.desvio_metros as desvio_bruto,
       p.lat as lat_proc, p.lon as lon_proc,
       p.precisao as precisao_proc, p.desvio_metros as desvio_proc
from bruto as b
full join processado as p using (id)
"""

# o mesmo SQL serve para qualquer base: `estagio` traz os campos originais e
# `segmentado` o que o segmentador extraiu de cada um deles
SQL_SEGMENTACAO = """
with j as (
    select s.*, g.logradouro_extraido, g.numero_extraido, g.complemento_extraido,
           g.localidade_extraido, g.cep_extraido
    from estagio as s
    left join segmentado as g using (id)
),
longo as (
    select 'logradouro' as campo, logradouro as original, logradouro_extraido as extraido from j
    union all select 'numero', numero, numero_extraido from j
    union all select 'complemento', complemento, complemento_extraido from j
    union all select 'localidade', localidade, localidade_extraido from j
    union all select 'cep', cep, cep_extraido from j
),
limpo as (
    select campo, original, nullif(trim(extraido), '') as extraido from longo
)
select campo,
       count(*) as registros,
       count(extraido) as extraidos,
       count(*) filter (where extraido is not null
                          and extraido is distinct from original) as diferentes
from limpo
group by campo
"""

SQL_DESLOCAMENTO = """
with pontos as (
    -- raio medio da Terra (IUGG), em metros
    select 2 * 6371008.8 * asin(sqrt(least(1.0,
               sin(radians(lat_proc - lat_bruto) / 2) ^ 2
               + cos(radians(lat_bruto)) * cos(radians(lat_proc))
               * sin(radians(lon_proc - lon_bruto) / 2) ^ 2))) as metros
    from par
    where lat_bruto is not null and lat_proc is not null
)
select count(*) as pares,
       avg(metros) as media,
       median(metros) as mediana,
       quantile_cont(metros, 0.75) as p75,
       quantile_cont(metros, 0.90) as p90,
       quantile_cont(metros, 0.99) as p99,
       count(*) filter (where metros < 1) as abaixo_1m,
       count(*) filter (where metros > 1000) as acima_1km
from pontos
"""

@contextmanager
def cronometrar(rotulo: str) -> Generator[None]:
    """Imprime o tempo gasto por uma etapa."""
    inicio = time.perf_counter()
    print(f"[{rotulo}] ...", flush=True)
    yield
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
    if campos["estado"] is None or campos["municipio"] is None:
        raise typer.BadParameter("--estado e --municipio sao obrigatorios")
    if chave is not None:
        if chave not in colunas:
            raise typer.BadParameter(f"coluna chave ausente na base: {chave!r}")
        if chave in COLUNAS_RESERVADAS:
            raise typer.BadParameter(
                f"--chave nao pode ser uma coluna reservada: {chave!r}"
            )
    if not any(campos[c] for c in CAMPOS_EXTRAIVEIS):
        raise typer.BadParameter(
            "informe ao menos uma coluna de endereco: --logradouro, --numero, "
            + "--complemento, --localidade, --cep ou --endereco"
        )

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
        origens = [campos[c] for c in ("logradouro", "numero", "complemento", "localidade")]
        partes = [texto(coluna) for coluna in origens if coluna is not None]
    if not partes:
        raise typer.BadParameter("nenhuma coluna de texto para segmentar")
    selecao.append(f"nullif(trim(concat_ws(' ', {', '.join(partes)})), '') as endereco")

    relacao = con.read_parquet(entrada)
    if limite > 0:
        relacao = relacao.limit(limite)
    relacao.project(", ".join(selecao)).write_parquet(str(destino), compression="zstd")

def montar_entradas(
    con: duckdb.DuckDBPyConnection,
    estagio: Path,
    segmentado: Path,
    pasta: Path,
    campos: dict[str, str | None],
    chave: str | None,
) -> dict[str, Path]:
    """Parquets de entrada do geocodebr: campos originais e campos extraidos."""
    disponiveis = [c for c in CAMPOS_ENDERECO if campos[c] is not None]
    identificacao = ["id"] + (["chave"] if chave is not None else [])
    fixos = [c for c in ("estado", "municipio") if c in disponiveis]
    variaveis = [c for c in disponiveis if c not in fixos]

    colunas_bruto = ", ".join([*identificacao, *fixos, *variaveis])
    bruto = pasta / "bruto_entrada.parquet"
    con.read_parquet(str(estagio)).project(colunas_bruto).write_parquet(
        str(bruto), compression="zstd"
    )

    # fallback campo a campo: extracao vazia mantem o valor original
    selecao = [f"s.{c} as {c}" for c in (*identificacao, *fixos)]
    for campo in variaveis:
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

def geocodificar(
    con: duckdb.DuckDBPyConnection,
    entrada: Path,
    destino: Path,
    campos: dict[str, str | None],
    n_cores: int,
) -> int:
    import geocodebr

    campos_endereco: dict[str, str | None] = {
        c: c for c in CAMPOS_GEOCODEBR if campos[c] is not None
    }
    resultado = cast(
        pa.Table,
        geocodebr.geocode(
            entrada,
            campos_endereco=campos_endereco,
            n_cores=n_cores if n_cores > 0 else None,
            verboso=True,
        ),
    )
    _ = con.register("resultado_geocode", resultado)
    _ = con.table("resultado_geocode").write_parquet(str(destino), compression="zstd")
    return resultado.num_rows

def registrar_visoes(
    con: duckdb.DuckDBPyConnection,
    estagio: Path,
    segmentado: Path,
    bruto: Path,
    processado: Path,
) -> None:
    _ = con.read_parquet(str(estagio)).to_view("estagio")
    _ = con.read_parquet(str(segmentado)).to_view("segmentado")
    colunas = "id, lat, lon, precisao, tipo_resultado, desvio_metros"
    _ = con.read_parquet(str(bruto)).project(colunas).to_view("bruto")
    _ = con.read_parquet(str(processado)).project(colunas).to_view("processado")
    _ = con.sql(SQL_GEOCODE)
    _ = con.sql(SQL_PAR)

def imprime(titulo: str, df: pd.DataFrame) -> None:
    print(f"\n{titulo}\n{'=' * len(titulo)}")
    print(df.to_string(index=False, float_format="{:,.2f}".format))

def comparar_segmentacao(
    con: duckdb.DuckDBPyConnection, campos: dict[str, str | None]
) -> pd.DataFrame:
    mapa = pd.DataFrame(
        {
            "campo": list(CAMPOS_EXTRAIVEIS),
            "mapeada": [campos[c] is not None for c in CAMPOS_EXTRAIVEIS],
        }
    )
    df = con.sql(SQL_SEGMENTACAO).df().merge(mapa, on="campo", how="left")
    df["extraidos_pct"] = 100 * df["extraidos"] / df["registros"]
    df["diferentes_pct"] = 100 * df["diferentes"] / df["registros"]
    return df

def comparar_cobertura(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    return con.sql(
        """
        select versao,
               count(*) as registros,
               count(lat) as geolocalizados,
               100.0 * count(lat) / count(*) as cobertura_pct,
               count(*) filter (where precisao = 'numero') as numero_exato,
               100.0 * count(*) filter (where precisao = 'numero') / count(lat)
                   as numero_exato_pct
        from geocode
        group by versao
        order by versao
        """
    ).df()

def comparar_precisao(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    df = con.sql(
        """
        select versao, coalesce(precisao, '(sem resultado)') as precisao,
               count(*) as n
        from geocode
        group by versao, precisao
        """
    ).df()
    df["freq_pct"] = 100 * df["n"] / df.groupby("versao")["n"].transform("sum")
    tabela = df.pivot(index="precisao", columns="versao", values="freq_pct").fillna(0.0)
    tabela.index.name = "precisao (% de cada versao)"
    return tabela.round(2).reset_index()

def comparar_desvio_total(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    return con.sql(
        """
        select versao,
               count(*) filter (where desvio_metros is not null) as com_desvio,
               avg(desvio_metros) as media,
               median(desvio_metros) as mediana,
               quantile_cont(desvio_metros, 0.75) as p75,
               quantile_cont(desvio_metros, 0.90) as p90,
               quantile_cont(desvio_metros, 0.99) as p99,
               100.0 * count(*) filter (where desvio_metros <= 100)
                   / count(desvio_metros) as ate_100m_pct,
               100.0 * count(*) filter (where desvio_metros > 1000)
                   / count(desvio_metros) as acima_1km_pct
        from geocode
        group by versao
        order by versao
        """
    ).df()

def comparar_desvio(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    return con.sql(
        """
        select versao,
               coalesce(precisao, '(sem resultado)') as precisao,
               count(*) as registros,
               count(desvio_metros) as com_desvio,
               avg(desvio_metros) as media,
               median(desvio_metros) as mediana,
               quantile_cont(desvio_metros, 0.75) as p75,
               quantile_cont(desvio_metros, 0.90) as p90,
               quantile_cont(desvio_metros, 0.99) as p99
        from geocode
        group by versao, precisao
        order by precisao, versao
        """
    ).df()

def comparar_pareado(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    return con.sql(
        """
        select count(*) as pares,
               count(lat_bruto) as geoc_bruto,
               count(lat_proc) as geoc_proc,
               count(*) filter (where lat_bruto is not null and lat_proc is not null)
                   as ambos,
               count(*) filter (where lat_bruto is null and lat_proc is not null)
                   as so_processado,
               count(*) filter (where lat_bruto is not null and lat_proc is null)
                   as so_bruto,
               count(*) filter (where precisao_bruto is distinct from precisao_proc)
                   as precisao_mudou
        from par
        """
    ).df()

def comparar_mudanca_precisao(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    df = con.sql(
        """
        select coalesce(precisao_bruto, '(sem)') as precisao_bruto,
               coalesce(precisao_proc, '(sem)') as precisao_proc,
               count(*) as n
        from par
        group by 1, 2
        """
    ).df()
    tabela = df.pivot(index="precisao_bruto", columns="precisao_proc", values="n")
    return tabela.fillna(0).astype(int).reset_index()

def comparar_delta_desvio(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    grupos = con.sql(
        """
        select case when precisao_bruto = precisao_proc
                    then 'mesma precisao' else 'precisao diferente' end as grupo,
               count(*) as n,
               avg(desvio_bruto) as media_bruto,
               avg(desvio_proc) as media_proc,
               median(desvio_bruto) as mediana_bruto,
               median(desvio_proc) as mediana_proc,
               avg(desvio_proc - desvio_bruto) as delta_medio,
               median(desvio_proc - desvio_bruto) as delta_mediano
        from par
        where desvio_bruto is not null and desvio_proc is not null
        group by grupo
        """
    ).df()
    todos = con.sql(
        """
        select 'todos os pares' as grupo,
               count(*) as n,
               avg(desvio_bruto) as media_bruto,
               avg(desvio_proc) as media_proc,
               median(desvio_bruto) as mediana_bruto,
               median(desvio_proc) as mediana_proc,
               avg(desvio_proc - desvio_bruto) as delta_medio,
               median(desvio_proc - desvio_bruto) as delta_mediano
        from par
        where desvio_bruto is not null and desvio_proc is not null
        """
    ).df()
    return pd.concat([todos, grupos], ignore_index=True)

def comparar_deslocamento(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    return con.sql(SQL_DESLOCAMENTO).df()
