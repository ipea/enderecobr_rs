import json
import sqlite3
import subprocess
from pathlib import Path
from typing import Annotated

import geocodebr
import enderecobr
import pandas as pd
import typer

app = typer.Typer(no_args_is_help=True, add_completion=False)


@app.command()
def main():
    con = sqlite3.connect("./dataset.sqlite")
    consulta = con.execute(
        "select endereco, origem, municipio, uf, (meta->>'latitude') as lat, (meta->>'longitude') as lon from enderecos where lat is not null and lon is not null;"
    )

    dados = [
        (str(e[0]), str(e[1]), str(e[2]), str(e[3]), float(e[4]), float(e[5]))
        for e in consulta.fetchall()
    ]

    enderecos_string = "\n".join([d[0] for d in dados])
    try:
        res = subprocess.run(
            [
                "cargo",
                "run",
                "--quiet",
                "--bin",
                "padronizar",
                "--features=experimental,cli",
                "estruturacao",
            ],
            input=enderecos_string,
            capture_output=True,
            text=True,
            check=True,
            cwd="../../",
        )
    except subprocess.CalledProcessError as e:
        # Captura o erro específico do subprocess
        print(f"Erro ao executar cargo: {e.returncode}")
        print(f"STDOUT:\n{e.stdout}")
        print(f"STDERR:\n{e.stderr}")
        return
    except Exception as e:
        # Captura outros erros (ex: cargo não encontrado)
        print(f"Erro inesperado: {type(e).__name__}: {e}")
        return

    saida = res.stdout

    bruto = {
        "original": [],
        "origem": [],
        "logradouro_padr": [],
        "numero_padr": [],
        "complemento_padr": [],
        "localidade_padr": [],
        "cep_padr": [],
        "municipio_padr": [],
        "estado_padr": [],
        "lat_original": [],
        "lon_original": [],
    }
    for (original, origem, mun, uf, lat, lon), endereco_str in zip(
        dados, saida.splitlines()
    ):
        end = json.loads(endereco_str)

        num_bruto = end.get("numero")
        if num_bruto is None:
            num_bruto = ""
        numero = enderecobr.padronizar_numeros_para_int(num_bruto)

        bruto["original"].append(original)
        bruto["origem"].append(origem)
        bruto["logradouro_padr"].append(end.get("logradouro"))
        bruto["numero_padr"].append(numero)
        bruto["complemento_padr"].append(end.get("complemento"))
        bruto["localidade_padr"].append(end.get("localidade"))
        bruto["cep_padr"].append(end.get("cep"))
        bruto["municipio_padr"].append(mun)
        bruto["estado_padr"].append(uf)
        bruto["lat_original"].append(lat)
        bruto["lon_original"].append(lon)

    df = pd.DataFrame(bruto)

    res: pd.DataFrame = geocodebr.geocode(
        df,
        campos_endereco={
            "estado": "estado_padr",
            "municipio": "municipio_padr",
            "logradouro": "logradouro_padr",
            "numero": "numero_padr",
            "cep": "cep_padr",
            "localidade": "localidade_padr",
        },
        padronizar_enderecos=False,
        n_cores=2,
    ).to_pandas()

    res.to_pickle("geolocalizado.pickle")


if __name__ == "__main__":
    app()
