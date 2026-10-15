import json
import sqlite3
import subprocess
from pathlib import Path
from typing import Annotated

import sklearn_crfsuite
import typer

from crf_endereco import teste_manual
from crf_endereco.preproc import ExtratorFeature

app = typer.Typer(no_args_is_help=True, add_completion=False)


def printa_segmentos(segmentos: list[dict[str, str]]):
    for s in segmentos:
        print(f"{s.get('tipo', '').title()}: {s.get('valor', '')}")


@app.command()
def main(
    tagger: Annotated[Path, typer.Argument(help="Path do tagger treinado")] = Path(
        "./tagger.crf"
    ),
):
    crf = sklearn_crfsuite.CRF(model_filename=str(tagger))
    extrator = ExtratorFeature()

    con = sqlite3.connect("./dataset.sqlite")
    consulta = con.execute("select endereco from enderecos;")

    enderecos = [str(e[0]) for e in consulta.fetchall()]
    segmentos_python: list[list[dict[str, str]]] = []

    for e in enderecos:
        campos = teste_manual.extrair_campos(crf, extrator, e)
        segmentos_python.append(teste_manual.coletar_segmentos(campos))

    ##########
    enderecos_string = "\n".join([str(e) for e in enderecos])
    res = subprocess.run(
        [
            "cargo",
            "run",
            "--quiet",
            "--bin",
            "padronizar",
            "--features=experimental,cli",
            "segmentar",
        ],
        input=enderecos_string,
        capture_output=True,
        text=True,
        check=True,
        cwd="../../",
    )
    saida = res.stdout

    ######

    n_diferentes = 0
    for endereco, resposta_rust_str, segmento_python in zip(
        enderecos, saida.splitlines(), segmentos_python, strict=True
    ):
        try:
            segmento_rust = json.loads(resposta_rust_str)
        except Exception as e:
            print("=============")
            print(f"Erro ao processar '{endereco}': {e}")
            print(f"Bruto: {resposta_rust_str}")
            break

        diferente = False
        for seg_rust, seg_python in zip(segmento_rust, segmento_python):
            if seg_rust.get("tipo") != seg_python.get("tipo") or seg_rust.get(
                "valor"
            ) != seg_python.get("valor"):
                diferente = True
                n_diferentes += 1
                break

        if diferente:
            print("-------------")
            print(endereco)
            print()
            print("[Python]")
            printa_segmentos(segmento_python)
            print()
            print("[Rust]")
            printa_segmentos(segmento_rust)

    con.close()
    print("------")
    print(
        f"Total Casos Diferentes: {n_diferentes}/{len(enderecos)} - {n_diferentes / len(enderecos):.2f}%"
    )


if __name__ == "__main__":
    app()
