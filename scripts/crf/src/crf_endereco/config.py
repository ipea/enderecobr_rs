"""Caminhos e ambiente do pipeline num unico lugar."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import typer
from dotenv import load_dotenv

from crf_endereco.ui import console

DIR_PROJETO = Path(__file__).resolve().parents[2]
DIR_REPO = DIR_PROJETO.parents[1]
DIR_DADOS = Path(os.environ.get("CRF_DATA_DIR") or DIR_PROJETO / "data")

CAMINHO_DATASET = DIR_DADOS / "anotado" / "dataset.sqlite"
CAMINHO_TAGGER = DIR_DADOS / "modelos" / "tagger.crf"
CAMINHO_CNEFE = Path(
    os.environ.get("CNEFE_PATH") or DIR_DADOS / "brutos" / "cnefe.parquet"
)
MUNICIPIOS = Path(
    os.environ.get("MUNICIPIOS_PATH") or DIR_REPO / "src" / "data" / "municipios.csv"
)


@dataclass(frozen=True)
class Config:
    """Ambiente resolvido para uma execucao (LLM e bases de apoio)."""

    api_url: str
    api_key: str
    api_model: str
    cnefe: Path = field(default=CAMINHO_CNEFE)
    municipios: Path = field(default=MUNICIPIOS)
    searx_url: str | None = None
    timeout_sql: float = 15.0
    # `strict: true` no schema das ferramentas e opcional: alguns backends
    # (`deepseek-v4.1-flash`, por exemplo) respondem HTTP 500 com ele.
    tools_estritas: bool = False

    @property
    def url_chat(self) -> str:
        return f"{self.api_url}/v1/chat/completions"


def carregar_config(env: Path = Path(".env")) -> Config:
    """Le o `.env` (quando existe) e resolve o ambiente da anotacao."""
    if env.is_file():
        load_dotenv(env)
    elif env.name != ".env":
        raise typer.BadParameter(f"Arquivo .env nao encontrado: {env}")

    searx_url = os.environ.get("SEARX_URL") or None
    if searx_url is None:
        console.print(
            "[yellow]SEARX_URL não definida; a busca web ficará indisponível.[/yellow]"
        )

    return Config(
        api_url=_exigir("API_URL"),
        api_key=_exigir("API_KEY"),
        api_model=_exigir("API_MODEL"),
        searx_url=searx_url,
        timeout_sql=_float("TIMEOUT_SQL", 15.0),
        tools_estritas=_booleano("API_TOOLS_STRICT", False),
    )


def _exigir(nome: str) -> str:
    valor = os.environ.get(nome)
    if not valor:
        raise typer.BadParameter(
            f"Variável de ambiente obrigatória ausente: {nome}. "
            "Defina-a no .env ou no ambiente."
        )
    return valor


def _float(nome: str, padrao: float) -> float:
    bruto = os.environ.get(nome)
    if not bruto:
        return padrao
    try:
        return float(bruto)
    except ValueError as erro:
        raise typer.BadParameter(
            f"Variável de ambiente {nome} deve ser numérica (recebido {bruto!r})."
        ) from erro


def _booleano(nome: str, padrao: bool) -> bool:
    bruto = os.environ.get(nome)
    if bruto is None or not bruto.strip():
        return padrao
    return bruto.strip().lower() not in {"0", "false", "nao", "não", "no", "off"}
