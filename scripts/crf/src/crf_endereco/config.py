"""Caminhos do pipeline (dados, modelos e saidas)."""

import os
from pathlib import Path

DIR_PROJETO = Path(__file__).resolve().parents[2]
DIR_REPO = DIR_PROJETO.parents[1]
DIR_DADOS = Path(os.environ.get("CRF_DATA_DIR") or DIR_PROJETO / "data")

CAMINHO_DATASET = DIR_DADOS / "anotado" / "dataset.sqlite"
CAMINHO_TAGGER = DIR_DADOS / "modelos" / "tagger.crf"
CAMINHO_CNEFE = Path(
    os.environ.get("CNEFE_PATH") or DIR_DADOS / "brutos" / "cnefe.parquet"
)
DIR_SAIDAS = DIR_DADOS / "saidas"
MUNICIPIOS = DIR_REPO / "src" / "data" / "municipios.csv"
