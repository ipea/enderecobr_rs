"""Prompts enviados a LLM."""

from pathlib import Path

from crf_endereco.config import Config

TEMPLATE_PROMPT_SISTEMA = Path(__file__).resolve().parent / "prompt_sistema.md"


def renderizar_prompt_sistema(config: Config) -> str:
    """Preenche o template do prompt de sistema com as ferramentas disponíveis."""
    ferramentas = [
        "- `responder`: submit the final result. Always use this tool to answer.",
        (
            "- `sql_query`: query CNEFE in DuckDB. Restrict by município and/or "
            "uf, always use LIMIT and avoid SELECT *."
        ),
    ]
    if config.searx_url:
        ferramentas.append("- `search`: search across several search engines.")
    ferramentas.append(
        "- `fetch_url`: fetch a URL and return its content as markdown (markitdown)."
    )

    template = TEMPLATE_PROMPT_SISTEMA.read_text(encoding="utf-8")
    return template.replace("{secao_ferramentas}", "\n".join(ferramentas))


def renderizar_prompt_usuario(endereco: str, extras: str, n_rodadas: int) -> str:
    return f"""Extra info (context only; it does NOT populate segments):
{extras}

Raw address:
{endereco}

You have {n_rodadas} rounds.
"""
