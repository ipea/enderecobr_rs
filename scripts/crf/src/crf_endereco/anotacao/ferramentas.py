"""Ferramentas que a LLM pode chamar (CNEFE, busca web, fetch)."""

from __future__ import annotations

import threading
from typing import Any

import duckdb
import markitdown
import requests

from crf_endereco.anotacao.cliente_http import USER_AGENT, ClienteHTTP
from crf_endereco.anotacao.config import Config
from crf_endereco.anotacao.ontologia import TIPOS_SEGMENTO
from crf_endereco.anotacao.resposta import ToolCall


def _criar_json_schema_funcao(
    nome: str,
    descricao: str,
    propriedades: dict[str, Any],
    requeridos: list[str],
    *,
    estrita: bool = False,
) -> dict[str, Any]:
    """Descreve uma ferramenta em `function`-calling.

    `estrita` liga `strict: true` no schema (JSON Schema mode). Fica desligado
    por padrão porque alguns backends recusam esse campo com HTTP 500 — o
    backend `deepseek-v4.1-flash` do IPEA, por exemplo. Ligue com
    `API_TOOLS_STRICT=1` quando o provedor suportar.
    """
    funcao: dict[str, Any] = {
        "name": nome,
        "description": descricao,
        "parameters": {
            "type": "object",
            "properties": propriedades,
            "required": requeridos,
            "additionalProperties": False,
        },
    }
    if estrita:
        funcao["strict"] = True
    return {"type": "function", "function": funcao}

def criar_ferramentas(config: Config) -> list[dict[str, Any]]:
    """Monta as ferramentas expostas à LLM, conforme a configuração."""
    estrita = config.tools_estritas
    ferramentas = [
        _criar_json_schema_funcao(
            "responder",
            "Submit the final answer to the request",
            {
                "segmentos": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "valor": {"type": "string"},
                            "tipo": {"type": "string", "enum": TIPOS_SEGMENTO},
                        },
                        "required": ["valor", "tipo"],
                        "additionalProperties": False,
                    },
                    "minItems": 1,
                },
                "comentario": {"type": "string"},
            },
            ["segmentos"],
            estrita=estrita,
        ),
        _criar_json_schema_funcao(
            "fetch_url",
            "Fetch the requested URL and return the result in markdown",
            {"url": {"type": "string", "description": "Requested URL"}},
            ["url"],
            estrita=estrita,
        ),
        _criar_json_schema_funcao(
            "sql_query",
            "Run a SQL query using DuckDB over CNEFE.",
            {"sql": {"type": "string", "description": "SQL to execute"}},
            ["sql"],
            estrita=estrita,
        ),
    ]

    if config.searx_url:
        ferramentas.append(
            _criar_json_schema_funcao(
                "search",
                "Search across several search engines.",
                {"query": {"type": "string", "description": "Search query"}},
                ["query"],
                estrita=estrita,
            )
        )

    return ferramentas

class Ferramentas:
    """Executa as ferramentas chamadas pela LLM (CNEFE, busca web, fetch)."""

    def __init__(self, config: Config, cliente: ClienteHTTP) -> None:
        self.config = config
        self.cliente = cliente
        self.md = markitdown.MarkItDown()

        # Conexão efêmera e privada da thread: DuckDB não é thread-safe, então
        # cada `Ferramentas` (e cada worker do modo lote) tem a sua.
        self.conn = duckdb.connect()
        self.conn.register("cnefe", self.conn.read_parquet(config.cnefe_path))
        self.conn.register("municipio", self.conn.read_csv(str(config.municipios_path)))

    def fechar(self) -> None:
        self.conn.close()

    def despachar(self, chamada: ToolCall) -> str:
        match chamada.nome:
            case "search":
                return self.buscar_web(chamada.argumentos.get("query", ""))
            case "sql_query":
                return self.consultar_sql(chamada.argumentos.get("sql", ""))
            case "fetch_url":
                return self.buscar_url(chamada.argumentos.get("url", ""))
            case _:
                return f"Requested tool {chamada.nome} does not exist"

    def buscar_web(self, query: str) -> str:
        if not self.config.searx_url:
            return "SEARX_URL is not set; web search is unavailable."

        try:
            res = self.cliente.obter(
                self.config.searx_url, params={"q": query, "format": "json"}
            )
            resultados = res.json().get("results", [])
        except (requests.RequestException, ValueError) as e:
            return f"An error occurred while searching for '{query}': {e!s}"

        blocos = []
        for resultado in resultados:
            blocos.append(
                f"""# {resultado.get("title", "")}
url: {resultado.get("url", "")}
motores de busca: {", ".join(resultado.get("engines", []))}
data publicação: {resultado.get("pubdate", [])}
conteúdo: {resultado.get("content", "")}

"""
            )
        return "\n".join(blocos)

    def buscar_url(self, url: str) -> str:
        try:
            res = self.cliente.obter(url, headers={"User-Agent": USER_AGENT})
            return str(self.md.convert(res).markdown)
        except (
            requests.RequestException,
            markitdown.MarkItDownException,
            ValueError,
            OSError,
        ) as e:
            return f"An error occurred while fetching '{url}': {e!s}"

    def consultar_sql(self, sql: str) -> str:
        # Watchdog: interrompe a query se passar de `timeout_sql` segundos.
        # `interrupt()` é thread-safe e deixa a conexão reutilizável.
        expirou = threading.Event()

        def _interromper() -> None:
            expirou.set()
            self.conn.interrupt()

        timer = threading.Timer(self.config.timeout_sql, _interromper)
        timer.start()
        try:
            consulta = self.conn.execute(sql)
            colunas = [str(col[0]) for col in consulta.description]
            resultado = consulta.fetchall()
        except duckdb.Error as e:
            if expirou.is_set():
                return (
                    f"The query exceeded the {self.config.timeout_sql:.0f}s timeout "
                    "and was cancelled. Restrict by município/uf and add a LIMIT. "
                    "(Or raise TIMEOUT_SQL.)"
                )
            return f"An error occurred while running the query: {e!s}"
        finally:
            timer.cancel()

        cabecalho = "|".join(colunas)
        corpo = "\n".join("|".join(str(v) for v in linha) for linha in resultado)
        return f"{cabecalho}\n---------\n{corpo}\n"
