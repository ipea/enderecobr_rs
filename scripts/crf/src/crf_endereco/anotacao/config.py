"""Configuracao da anotacao por LLM (`.env`)."""

import os
from dataclasses import dataclass
from pathlib import Path

import typer
from dotenv import load_dotenv
from rich.console import Console

from crf_endereco.config import CAMINHO_CNEFE, MUNICIPIOS

console = Console()

console = Console()

@dataclass(frozen=True)
class Config:
    """Variáveis de ambiente resolvidas para uma execução."""

    api_url: str
    api_key: str
    api_model: str
    cnefe_path: str
    municipios_path: Path
    timeout_sql: float = 15.0
    searx_url: str | None = None
    # `strict: true` no schema das ferramentas é opcional: alguns backends
    # (`deepseek-v4.1-flash`, por exemplo) respondem HTTP 500 com ele.
    tools_estritas: bool = False

    @property
    def url_chat(self) -> str:
        return f"{self.api_url}/v1/chat/completions"

def carregar_config(env_path: Path) -> Config:
    """Carrega o `.env` e valida as variáveis obrigatórias."""
    if env_path.is_file():
        load_dotenv(env_path)
    elif env_path.name != ".env":
        raise typer.BadParameter(f"Arquivo .env não encontrado: {env_path}")

    def exigir(nome: str) -> str:
        valor = os.environ.get(nome)
        if not valor:
            raise typer.BadParameter(
                f"Variável de ambiente obrigatória ausente: {nome}. "
                "Defina-a no .env ou no ambiente."
            )
        return valor

    def opcional_float(nome: str, padrao: float) -> float:
        bruto = os.environ.get(nome)
        if not bruto:
            return padrao
        try:
            return float(bruto)
        except ValueError as e:
            raise typer.BadParameter(
                f"Variável de ambiente {nome} deve ser numérica (recebido {bruto!r})."
            ) from e

    def opcional_bool(nome: str, padrao: bool) -> bool:
        bruto = os.environ.get(nome)
        if bruto is None or not bruto.strip():
            return padrao
        return bruto.strip().lower() not in {"0", "false", "nao", "não", "no", "off"}

    searx_url = os.environ.get("SEARX_URL")
    if not searx_url:
        console.print(
            "[yellow]SEARX_URL não definida; a busca web ficará indisponível.[/yellow]"
        )

    return Config(
        api_url=exigir("API_URL"),
        api_key=exigir("API_KEY"),
        api_model=exigir("API_MODEL"),
        cnefe_path=str(CAMINHO_CNEFE),
        municipios_path=Path(os.environ.get("MUNICIPIOS_PATH") or MUNICIPIOS),
        timeout_sql=opcional_float("TIMEOUT_SQL", 15.0),
        searx_url=searx_url,
        tools_estritas=opcional_bool("API_TOOLS_STRICT", False),
    )
