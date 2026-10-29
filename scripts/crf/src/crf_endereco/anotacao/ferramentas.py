"""Ferramentas que a LLM pode chamar (CNEFE, busca web, fetch)."""

from __future__ import annotations

import threading
from collections.abc import Mapping
from typing import Any

import duckdb
import markitdown
import requests

from crf_endereco.anotacao.cliente_http import (
    USER_AGENT,
    ClienteHTTP,
    ErroHTTP,
)
from crf_endereco.anotacao.ontologia import TIPOS_SEGMENTO
from crf_endereco.config import Config


# Primeira palavra aceita em `sql_query`: a ferramenta executa SQL escrito pela
# LLM, então só leitura passa. Sem isso o modelo poderia escrever arquivos
# (`COPY ... TO`), instalar extensões ou anexar outro banco.
CONSULTAS_PERMITIDAS = frozenset({"select", "with", "describe", "summarize", "explain"})


def validar_consulta(sql: str) -> str:
    """Devolve a consulta normalizada ou levanta `ValueError` se não for leitura."""
    limpo = sql.strip().rstrip(";").strip()
    if not limpo:
        raise ValueError("consulta vazia")
    if ";" in limpo:
        raise ValueError("uma instrução por chamada")
    primeira = limpo.split(None, 1)[0].lower()
    if primeira not in CONSULTAS_PERMITIDAS:
        raise ValueError(
            "apenas consultas de leitura ("
            + ", ".join(sorted(CONSULTAS_PERMITIDAS))
            + ")"
        )
    return limpo


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
    ]

    if config.com_cnefe:
        ferramentas.insert(
            1,
            _criar_json_schema_funcao(
                "sql_query",
                "Run a SQL query using DuckDB over CNEFE.",
                {"sql": {"type": "string", "description": "SQL to execute"}},
                ["sql"],
                estrita=estrita,
            ),
        )

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
        # cada `Ferramentas` (e cada worker do modo lote) tem a sua. Só existe
        # quando a ferramenta de SQL está ligada (`--com-cnefe`).
        self.conn: duckdb.DuckDBPyConnection | None = None
        if config.com_cnefe:
            self.conn = duckdb.connect()
            self.conn.register("cnefe", self.conn.read_parquet(config.cnefe))
            self.conn.register(
                "municipio", self.conn.read_csv(str(config.municipios))
            )

    def fechar(self) -> None:
        if self.conn is not None:
            self.conn.close()
            self.conn = None

    @property
    def conexao(self) -> duckdb.DuckDBPyConnection:
        """Conexao do DuckDB, exigindo a ferramenta ligada (`--com-cnefe`)."""
        if self.conn is None:
            raise RuntimeError("sql_query desligada: rode com --com-cnefe")
        return self.conn

    def despachar(self, nome: str, argumentos: Mapping[str, Any]) -> str:
        match nome:
            case "search":
                return self.buscar_web(str(argumentos.get("query", "")))
            case "sql_query":
                return self.consultar_sql(str(argumentos.get("sql", "")))
            case "fetch_url":
                return self.buscar_url(str(argumentos.get("url", "")))
            case _:
                return f"Requested tool {nome} does not exist"

    def buscar_web(self, query: str) -> str:
        if not self.config.searx_url:
            return "SEARX_URL is not set; web search is unavailable."

        try:
            res = self.cliente.obter(
                self.config.searx_url, params={"q": query, "format": "json"}
            )
            resultados = res.json().get("results", [])
        except (requests.RequestException, ErroHTTP, ValueError) as e:
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
            ErroHTTP,
            markitdown.MarkItDownException,
            ValueError,
            OSError,
        ) as e:
            return f"An error occurred while fetching '{url}': {e!s}"

    def consultar_sql(self, sql: str) -> str:
        """Executa SQL arbitrario da LLM sobre `cnefe`/`municipio`.

        E o objetivo da ferramenta: a LLM consulta a base livremente. O sandbox
        e o DuckDB local (efemero, por thread, so com as duas tabelas
        registradas) mais o `interrupt()` do watchdog — nao ha escrita nem
        usuario no caminho.
        """
        if self.conn is None:
            return "The SQL tool is disabled in this run; answer without it."
        try:
            consulta_sql = validar_consulta(sql)
        except ValueError as erro:
            return f"Query rejected: {erro!s}"
        # Watchdog: interrompe a query se passar de `timeout_sql` segundos.
        # `interrupt()` e thread-safe e deixa a conexao reutilizavel.
        expirou = threading.Event()

        def _interromper() -> None:
            expirou.set()
            self.conexao.interrupt()

        timer = threading.Timer(self.config.timeout_sql, _interromper)
        timer.start()
        try:
            consulta = self.conexao.execute(consulta_sql)
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
