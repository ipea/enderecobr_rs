import numpy as np
import pandas as pd

RAIO_TERRA_M = 6_371_008.8
COLUNAS_COORDENADA = ["lat_original", "lon_original", "lat", "lon"]


def adicionar_distancia(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for coluna in COLUNAS_COORDENADA:
        df[coluna] = pd.to_numeric(df[coluna], errors="coerce")
    lat1 = np.radians(df["lat_original"].to_numpy(dtype="float64"))
    lat2 = np.radians(df["lat"].to_numpy(dtype="float64"))
    delta_lat = lat2 - lat1
    delta_lon = np.radians(
        df["lon"].to_numpy(dtype="float64")
        - df["lon_original"].to_numpy(dtype="float64")
    )
    haversine = (
        np.sin(delta_lat / 2) ** 2
        + np.cos(lat1) * np.cos(lat2) * np.sin(delta_lon / 2) ** 2
    )
    haversine = np.clip(haversine, 0.0, 1.0)
    df["distancia_metros"] = 2 * RAIO_TERRA_M * np.arcsin(np.sqrt(haversine))
    df.loc[df[COLUNAS_COORDENADA].isna().any(axis=1), "distancia_metros"] = np.nan
    return df


def estatisticas_distancia(
    df: pd.DataFrame,
    dimensao: str,
    percentis: tuple[float, ...] = (0.5, 0.75, 0.9, 0.95, 0.99),
) -> pd.DataFrame:
    base = df.dropna(subset=["distancia_metros", dimensao])
    n_total = len(base)
    estatisticas = base.groupby(dimensao)["distancia_metros"].agg(
        n="count",
        media="mean",
        mediana="median",
        desvio_padrao="std",
        minimo="min",
        maximo="max",
    )
    quantis = base.groupby(dimensao)["distancia_metros"].quantile(percentis).unstack()
    quantis.columns = [f"p{int(q * 100)}" for q in quantis.columns]
    resultado = estatisticas.join(quantis)
    resultado["freq_registros"] = 100 * resultado["n"] / n_total
    return resultado.sort_values("media", ascending=False)


def frequencia_precisao(df: pd.DataFrame, dimensao: str | None = None) -> pd.DataFrame:
    chaves = ["precisao"] if dimensao is None else [dimensao, "precisao"]
    contagem = df.groupby(chaves, dropna=False).size().rename("n").reset_index()
    if dimensao is None:
        contagem["freq"] = 100 * contagem["n"] / contagem["n"].sum()
        return contagem.sort_values("n", ascending=False)
    contagem["freq"] = (
        100 * contagem["n"] / contagem.groupby(dimensao)["n"].transform("sum")
    )
    return contagem.pivot(index=dimensao, columns="precisao", values="freq").fillna(0.0)


def printa(dataframe):
    print(dataframe.to_string(index=True, float_format="{:.2f}".format))


df = pd.read_pickle("geolocalizado.pickle")
df = adicionar_distancia(df)

print("\nDistancias por Estado\n==============")
printa(estatisticas_distancia(df, "estado_padr"))

print("\nDistancias por Origem\n==============")
printa(estatisticas_distancia(df, "origem"))


print("\nDistancias por Precisão\n==============")
printa(estatisticas_distancia(df, "precisao"))

print("\nFrequência de Precisão\n==============")
printa(frequencia_precisao(df))

print("\nFrequência de Precisão por Estado\n==============")
printa(frequencia_precisao(df, "estado_padr"))

print("\nFrequência de Precisão por Origem\n==============")
printa(frequencia_precisao(df, "origem"))
