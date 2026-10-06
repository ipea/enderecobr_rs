#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "duckdb>=1.4.1",
#     "markitdown[pdf,docx,xls,xlsx]",
#     "python-dotenv",
#     "requests",
#     "rich",
#     "typer",
# ]
# ///
"""Etiqueta endereços brasileiros brutos em campos rotulados.

O script usa uma LLM com *tool-calling* (loop reAct) para segmentar o endereço
em spans verbo-verbatim. A LLM pode consultar o CNEFE (DuckDB), buscar na web
(SearxNG) e baixar URLs (MarkItDown) quando o trecho for ambíguo.

Uso:
    # Um endereço avulso
    uv run etiquetar.py etiquetar "R ALCIDES CARNEIRO LEAL 71 APTO 104" \\
        --extras "Municipio: Recife/PE" --env .env

    # Lote: processa os pendentes do banco gerado por dataset_etiquetacao.py
    uv run etiquetar.py lote dataset.sqlite --env .env

A ontologia de rótulos fica em `prompt_sistema.md` (prompt) e `ONTOLOGIA.md`
(notas de pós-processamento).
"""

from __future__ import annotations

import json
import os
import random
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, cast

import duckdb
import markitdown
import requests
import typer
from dotenv import load_dotenv
from rich.console import Console
from rich.pretty import pprint
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    TextColumn,
    TimeElapsedColumn,
)

# --- Caminhos -------------------------------------------------------------

DIR_MODULO = Path(__file__).resolve().parent
# scripts/crf/src/crf_endereco -> <repo>/src/data/municipios.csv
MUNICIPIOS_PADRAO = DIR_MODULO.parents[3] / "src" / "data" / "municipios.csv"
TEMPLATE_PROMPT_SISTEMA = DIR_MODULO / "prompt_sistema.md"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:156.0) Gecko/20100101 Firefox/156.0"
)

console = Console()

# --- Configuração ---------------------------------------------------------


@dataclass(frozen=True)
class Config:
    """Variáveis de ambiente resolvidas para uma execução."""

    api_url: str
    api_key: str
    api_model: str
    cnefe_path: str
    municipios_path: Path
    searx_url: str | None = None

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

    searx_url = os.environ.get("SEARX_URL")
    if not searx_url:
        console.print(
            "[yellow]SEARX_URL não definida; a busca web ficará indisponível.[/yellow]"
        )

    return Config(
        api_url=exigir("API_URL"),
        api_key=exigir("API_KEY"),
        api_model=exigir("API_MODEL"),
        cnefe_path=exigir("CNEFE_PATH"),
        municipios_path=Path(os.environ.get("MUNICIPIOS_PATH", MUNICIPIOS_PADRAO)),
        searx_url=searx_url,
    )


# --- Prompts --------------------------------------------------------------


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


# --- Esquemas das ferramentas (function calling) --------------------------

TIPOS_SEGMENTO = [
    "logradouro",
    "logradouro_interno",
    "numero",
    "modificador_numero",
    "complemento",
    "empreendimento",
    "parcela",
    "cadastro",
    "descricao_area",
    "quilometragem_via",
    "referencia",
    "denominacao",
    "localidade",
    "cep",
    "municipio",
    "uf",
    "ruido",
    "outros",
]


def _criar_json_schema_funcao(
    nome: str,
    descricao: str,
    propriedades: dict[str, Any],
    requeridos: list[str],
) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": nome,
            "description": descricao,
            "parameters": {
                "type": "object",
                "properties": propriedades,
                "required": requeridos,
                "additionalProperties": False,
            },
            "strict": True,
        },
    }


def criar_ferramentas(config: Config) -> list[dict[str, Any]]:
    """Monta as ferramentas expostas à LLM, conforme a configuração."""
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
        ),
        _criar_json_schema_funcao(
            "fetch_url",
            "Fetch the requested URL and return the result in markdown",
            {"url": {"type": "string", "description": "Requested URL"}},
            ["url"],
        ),
        _criar_json_schema_funcao(
            "sql_query",
            "Run a SQL query using DuckDB over CNEFE.",
            {"sql": {"type": "string", "description": "SQL to execute"}},
            ["sql"],
        ),
    ]

    if config.searx_url:
        ferramentas.append(
            _criar_json_schema_funcao(
                "search",
                "Search across several search engines.",
                {"query": {"type": "string", "description": "Search query"}},
                ["query"],
            )
        )

    return ferramentas


# --- Modelos de resposta da LLM -------------------------------------------


@dataclass
class ToolCall:
    idx: str
    nome: str
    argumentos: Any


@dataclass
class Segmento:
    valor: str
    tipo: str


@dataclass
class RespostaFinal:
    segmentos: list[Segmento]
    comentario: str | None


@dataclass
class RespostaModelo:
    resposta: str | None
    raciociono: str
    tool_calls: list[ToolCall]
    message_original: Any

    def obter_resposta_final(self) -> ToolCall | None:
        return next((c for c in self.tool_calls if c.nome == "responder"), None)


def estruturar_tool_calls(message: dict[str, Any]) -> list[ToolCall]:
    resultado: list[ToolCall] = []
    for call in message.get("tool_calls", []):
        funcao = call.get("function", {})
        try:
            argumentos = json.loads(funcao.get("arguments"))
        except (json.JSONDecodeError, TypeError):
            continue

        resultado.append(
            ToolCall(
                idx=call.get("id", ""),
                nome=funcao.get("name", ""),
                argumentos=argumentos,
            )
        )
    return resultado


def estruturar_resposta_modelo(resposta_bruta: dict[str, Any]) -> RespostaModelo:
    message = resposta_bruta.get("choices", [{}])[0].get("message", {})
    return RespostaModelo(
        resposta=message.get("content"),
        raciociono=message.get("reasoning", ""),
        tool_calls=estruturar_tool_calls(message),
        message_original=message,
    )


def processar_resultado_final(chamada: ToolCall) -> RespostaFinal:
    """Converte a chamada `responder` na resposta final estruturada."""
    segmentos = [
        Segmento(valor=str(seg.get("valor", "")), tipo=str(seg.get("tipo", "")))
        for seg in chamada.argumentos.get("segmentos", [])
    ]
    return RespostaFinal(
        segmentos=segmentos, comentario=chamada.argumentos.get("comentario")
    )


# --- Ferramentas ----------------------------------------------------------


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
        try:
            consulta = self.conn.execute(sql)
            colunas = [str(col[0]) for col in consulta.description]
            resultado = consulta.fetchall()
        except duckdb.Error as e:
            return f"An error occurred while running the query: {e!s}"

        cabecalho = "|".join(colunas)
        corpo = "\n".join("|".join(str(v) for v in linha) for linha in resultado)
        return f"{cabecalho}\n---------\n{corpo}\n"


# --- HTTP -----------------------------------------------------------------

ERROS_TRANSITORIOS = (
    requests.Timeout,
    requests.ConnectionError,
    requests.HTTPError,
    requests.JSONDecodeError,
)


class ClienteHTTP:
    """Cliente HTTP com retry para erros transientes.

    Concentraliza o backoff exponencial + jitter num único lugar, reusado tanto
    nas chamadas à LLM (`enviar_json`) quanto nas ferramentas de busca e fetch
    de páginas (`obter`).
    """

    def __init__(
        self,
        console: Console,
        n_tentativas: int = 5,
        delay_base: float = 2.0,
        timeout_conexao: float = 10.0,
    ) -> None:
        self.console: Console = console
        self.n_tentativas = n_tentativas
        self.delay_base = delay_base
        self.timeout_conexao = timeout_conexao
        self.sessao = requests.Session()
        self.sessao.trust_env = True

    def obter(
        self, url: str, *, timeout: float = 30.0, **kwargs: Any
    ) -> requests.Response:
        """GET com retry; retorna a resposta bruta."""
        return cast(requests.Response, self._requisitar("GET", url, timeout, **kwargs))

    def enviar_json(
        self,
        url: str,
        payload: dict[str, Any],
        *,
        timeout: float = 300.0,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """POST com retry; decodifica e retorna o corpo JSON."""
        return cast(
            dict[str, Any],
            self._requisitar(
                "POST", url, timeout, json=payload, decodificar=True, **kwargs
            ),
        )

    def _requisitar(
        self,
        metodo: str,
        url: str,
        timeout: float,
        *,
        decodificar: bool = False,
        **kwargs: Any,
    ) -> Any:
        """Executa uma requisição, reenviando em erros transientes."""
        for tentativa in range(self.n_tentativas):
            try:
                resposta = self.sessao.request(
                    metodo, url, timeout=(self.timeout_conexao, timeout), **kwargs
                )
                resposta.raise_for_status()
                return resposta.json() if decodificar else resposta
            except (
                requests.Timeout,
                requests.ConnectionError,
                requests.HTTPError,
                requests.JSONDecodeError,
            ) as e:
                if tentativa == self.n_tentativas - 1:
                    raise
                delay = self.delay_base * (2**tentativa - 1) + random.uniform(0, 5)
                self.console.print(
                    f"[yellow]Tentativa {tentativa + 1}/{self.n_tentativas} "
                    f"falhou: {e}. Retentando em {delay:.2f}s…[/yellow]"
                )
                time.sleep(delay)

        raise RuntimeError("Não foi possível realizar a requisição.")


def realizar_requisicao(
    cliente: ClienteHTTP, config: Config, messages: list[dict[str, Any]]
) -> dict[str, Any]:
    return cliente.enviar_json(
        config.url_chat,
        {
            "model": config.api_model,
            "messages": messages,
            "tools": criar_ferramentas(config),
            "temperature": 0.3,
        },
        headers={
            "Authorization": f"Bearer {config.api_key}",
            "Content-Type": "application/json",
        },
    )


# --- Contexto de execução -------------------------------------------------


@dataclass
class Contexto:
    """Reúne a configuração, o cliente HTTP e as ferramentas de uma execução."""

    config: Config
    cliente: ClienteHTTP
    ferramentas: Ferramentas
    console: Console

    @classmethod
    def criar(cls, config: Config, console: Console) -> Contexto:
        cliente = ClienteHTTP(console=console)
        return cls(
            config=config,
            cliente=cliente,
            ferramentas=Ferramentas(config, cliente),
            console=console,
        )

    def fechar(self) -> None:
        self.ferramentas.fechar()


# --- Validação ------------------------------------------------------------


def validar_resposta_final(
    endereco: str, resposta: RespostaFinal
) -> tuple[str, str | None]:
    """Confere que cada segmento é um trecho verbatim e na ordem do endereço.

    Retorna a visualização anotada e, se houver, a descrição dos problemas.
    """
    ultima_pos = 0
    problemas: list[str] = []
    visualizacao: list[str] = []

    for i, seg in enumerate(resposta.segmentos):
        posicao = endereco.find(seg.valor, ultima_pos)

        if posicao == -1:
            problemas.append(
                f"Could not locate segment #{i + 1}: {seg.valor} ({seg.tipo}) "
            )
            continue

        if posicao != ultima_pos:
            visualizacao.append(endereco[ultima_pos:posicao])

        fim = posicao + len(seg.valor)
        visualizacao.append(f"{endereco[posicao:fim]} [{seg.tipo}]")
        ultima_pos = fim

    if ultima_pos != len(endereco):
        visualizacao.append(endereco[ultima_pos:])

    problemas_str = "\n".join(problemas) if problemas else None
    return "\n".join(visualizacao), problemas_str


# --- Loop reAct -----------------------------------------------------------


class ErroSegmentacao(RuntimeError):
    """Não foi possível obter uma segmentação válida."""


def segmentar(
    contexto: Contexto,
    endereco: str,
    extras: str,
    *,
    n_iter: int = 10,
    tolerancia_erro: int = 2,
) -> RespostaFinal:
    """Roda o loop reAct até obter uma segmentação válida."""
    config = contexto.config
    console = contexto.console
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": renderizar_prompt_sistema(config)},
        {
            "role": "user",
            "content": renderizar_prompt_usuario(endereco, extras, n_iter),
        },
    ]
    erros_consecutivos = 0

    for i in range(n_iter):
        console.rule(f"Iteração {i + 1}/{n_iter}")

        resposta = estruturar_resposta_modelo(
            realizar_requisicao(contexto.cliente, config, messages)
        )
        messages.append(resposta.message_original)

        if resposta.raciociono:
            console.print(resposta.raciociono, style="dim italic")
        if resposta.resposta:
            console.print(resposta.resposta)

        chamada_final = resposta.obter_resposta_final()
        if chamada_final is not None:
            resultado = processar_resultado_final(chamada_final)
            visualizacao, erro = validar_resposta_final(endereco, resultado)
            console.print(visualizacao)

            if erro is None:
                return resultado

            erros_consecutivos += 1
            if erros_consecutivos > tolerancia_erro:
                raise ErroSegmentacao(
                    f"Validação falhou {erros_consecutivos} vezes seguidas:\n{erro}"
                )
            messages.append(
                {
                    "role": "user",
                    "content": f"An error occurred while validating your segmentation. Fix it and submit again.\n{erro}",
                }
            )
            continue

        for chamada in resposta.tool_calls:
            console.print(f"[bold]{chamada.nome}[/bold] {chamada.argumentos}")
            saida = contexto.ferramentas.despachar(chamada)
            console.print(saida)
            messages.append(
                {"role": "tool", "tool_call_id": chamada.idx, "content": saida}
            )

        if i == n_iter - 1:
            console.print("[bold red]Última iteração[/bold red]")
            messages.append(
                {
                    "role": "user",
                    "content": "Final round - Give your answer now or abstain",
                }
            )

    raise ErroSegmentacao(f"Sem resposta final após {n_iter} iterações.")


# --- Lote (dataset SQLite) ------------------------------------------------


@dataclass(frozen=True)
class LinhaPendente:
    """Uma linha ainda não processada do dataset de etiquetagem."""

    id: int
    endereco: str
    extras: str


def abrir_banco(caminho: Path) -> sqlite3.Connection:
    """Abre o SQLite gerado por `dataset_etiquetacao.py`."""
    if not caminho.is_file():
        raise typer.BadParameter(f"Banco de dados não encontrado: {caminho}")
    conn = sqlite3.connect(str(caminho))
    conn.row_factory = sqlite3.Row
    return conn


def selecionar_pendentes(
    conn: sqlite3.Connection,
    *,
    limite: int | None = None,
    lote: str | None = None,
    incluir_erros: bool = False,
) -> list[LinhaPendente]:
    """Seleciona as linhas a processar: pendentes e, opcionalmente, com erro.

    Consulta estática, só com parâmetros nomeados: `incluir_erros` liga/desliga
    o ramo de erros, `limite` nulo vira `-1` (sem limite no SQLite) e `lote`
    nulo desativa o filtro por lote.
    """
    linhas = cast(
        list[sqlite3.Row],
        conn.execute(
            """
            SELECT id, endereco, extras FROM enderecos
            WHERE (
                resposta_llm IS NULL
                OR (:incluir_erros AND json_extract(resposta_llm, '$.erro') IS NOT NULL)
            )
              AND (:lote IS NULL OR lote = :lote)
            ORDER BY random()
            LIMIT COALESCE(:limite, -1)
            """,
            {"incluir_erros": incluir_erros, "lote": lote, "limite": limite},
        ).fetchall(),
    )

    return [
        LinhaPendente(
            id=cast(int, linha["id"]),
            endereco=cast(str, linha["endereco"]),
            extras=cast(str, linha["extras"]),
        )
        for linha in linhas
    ]


def serializar_sucesso(resultado: RespostaFinal) -> str:
    """Serializa a segmentação da LLM (o valor gravado em `resposta_llm`)."""
    return json.dumps(
        {
            "segmentos": [asdict(segmento) for segmento in resultado.segmentos],
            "comentario": resultado.comentario,
        },
        ensure_ascii=False,
    )


def serializar_erro(mensagem: str) -> str:
    """Marca a linha como falha (recuperável via `--retentar-erros`)."""
    return json.dumps({"erro": mensagem}, ensure_ascii=False)


def gravar_resposta(
    conn: sqlite3.Connection,
    linha: LinhaPendente,
    resposta_llm: str,
    llm: str,
) -> None:
    """Grava o resultado de uma linha e commita (progresso persistido)."""
    _ = conn.execute(
        """
        UPDATE enderecos
        SET resposta_llm = ?, data_processamento = ?, llm = ?
        WHERE id = ?
        """,
        (resposta_llm, datetime.now(UTC).isoformat(), llm, linha.id),
    )
    conn.commit()


@dataclass(frozen=True)
class OpcoesLote:
    """Parâmetros do loop reAct e do paralelismo de uma execução em lote."""

    iteracoes: int
    tolerancia_erro: int
    concorrencia: int


class FabricaContextos:
    """Cria um `Contexto` por thread de trabalho.

    `Contexto` abre uma conexão DuckDB, que não é thread-safe; uma instância
    por worker evita compartilhar conexão entre threads.
    """

    def __init__(self, config: Config, console: Console) -> None:
        self.config: Config = config
        self.console: Console = console
        self._local: threading.local = threading.local()
        self._criados: list[Contexto] = []
        self._lock: threading.Lock = threading.Lock()

    def obter(self) -> Contexto:
        contexto: Contexto | None = getattr(self._local, "contexto", None)
        if contexto is None:
            contexto = Contexto.criar(self.config, self.console)
            self._local.contexto = contexto
            with self._lock:
                self._criados.append(contexto)
        return contexto

    def fechar(self) -> None:
        with self._lock:
            criados, self._criados = self._criados, []
        for contexto in criados:
            contexto.fechar()


def processar_linha(
    fabrica: FabricaContextos, linha: LinhaPendente, opcoes: OpcoesLote
) -> tuple[LinhaPendente, str]:
    """Segmenta uma linha; falha de segmentação vira `{"erro": ...}`.

    A criação do contexto fica fora do `try`: um erro de ambiente (ex.: CNEFE
    inacessível) deve abortar o lote, não marcar cada linha como erro.
    """
    contexto = fabrica.obter()
    try:
        resultado = segmentar(
            contexto,
            linha.endereco,
            linha.extras,
            n_iter=opcoes.iteracoes,
            tolerancia_erro=opcoes.tolerancia_erro,
        )
    except Exception as e:  # noqa: BLE001 — a falha é o resultado da linha
        return linha, serializar_erro(f"{type(e).__name__}: {e}")
    return linha, serializar_sucesso(resultado)


@dataclass
class ResumoLote:
    """Contagem final de uma execução em lote."""

    total: int = 0
    sucesso: int = 0
    erro: int = 0


def executar_lote(
    conn: sqlite3.Connection,
    config: Config,
    linhas: list[LinhaPendente],
    opcoes: OpcoesLote,
    *,
    console_llm: Console,
) -> ResumoLote:
    """Processa as linhas (sequencial ou paralelo) e grava cada resposta.

    Os workers só produzem resultado; a escrita no SQLite acontece na thread
    principal, à medida que os futuros completam.
    """
    fabrica = FabricaContextos(config, console_llm)
    resumo = ResumoLote(total=len(linhas))

    progresso = Progress(
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        console=Console(stderr=True),
    )

    pool = ThreadPoolExecutor(max_workers=opcoes.concorrencia)
    try:
        with progresso:
            tarefa = progresso.add_task("Etiquetando", total=len(linhas))
            futuros = [
                pool.submit(processar_linha, fabrica, linha, opcoes) for linha in linhas
            ]
            for futuro in as_completed(futuros):
                linha, resposta_json = futuro.result()
                gravar_resposta(conn, linha, resposta_json, config.api_model)
                conteudo = cast(dict[str, object], json.loads(resposta_json))
                if "erro" in conteudo:
                    resumo.erro += 1
                else:
                    resumo.sucesso += 1
                progresso.advance(tarefa)
    finally:
        pool.shutdown(wait=True, cancel_futures=True)
        fabrica.fechar()

    return resumo


# --- CLI ------------------------------------------------------------------

app = typer.Typer(no_args_is_help=True, add_completion=False)


@app.command()
def etiquetar(
    endereco: Annotated[str, typer.Argument(help="Endereço bruto a segmentar.")],
    extras: Annotated[
        str,
        typer.Option(
            "--extras",
            "-e",
            help="Informação extra de contexto (NÃO popula segmentos).",
        ),
    ] = "",
    env: Annotated[
        Path,
        typer.Option("--env", help="Caminho do arquivo .env."),
    ] = Path(".env"),
    iteracoes: Annotated[
        int,
        typer.Option(
            "--iteracoes", "-n", min=1, help="Máximo de rodadas do loop reAct."
        ),
    ] = 10,
    tolerancia_erro: Annotated[
        int,
        typer.Option(
            "--tolerancia-erro",
            min=0,
            help="Falhas de validação consecutivas antes de abortar.",
        ),
    ] = 2,
    saida: Annotated[
        Path | None,
        typer.Option("--saida", "-o", help="Arquivo JSON de saída (padrão: stdout)."),
    ] = None,
) -> None:
    """Segmenta um endereço bruto em campos rotulados usando uma LLM."""
    contexto = Contexto.criar(carregar_config(env), console)
    try:
        resultado = segmentar(
            contexto,
            endereco,
            extras,
            n_iter=iteracoes,
            tolerancia_erro=tolerancia_erro,
        )
    finally:
        contexto.fechar()

    console.rule("Resultado final")
    pprint(resultado)

    dados = {
        "endereco": endereco,
        "extras": extras,
        "segmentos": [asdict(seg) for seg in resultado.segmentos],
        "comentario": resultado.comentario,
    }
    texto = json.dumps(dados, ensure_ascii=False, indent=2)

    if saida:
        saida.write_text(texto, encoding="utf-8")
        console.print(f"[green]Salvo em {saida}[/green]")
    else:
        console.print(texto)


@app.command()
def lote(
    banco: Annotated[
        Path, typer.Argument(help="SQLite gerado por dataset_etiquetacao.py.")
    ],
    env: Annotated[
        Path,
        typer.Option("--env", help="Caminho do arquivo .env."),
    ] = Path(".env"),
    iteracoes: Annotated[
        int,
        typer.Option(
            "--iteracoes", "-n", min=1, help="Máximo de rodadas do loop reAct."
        ),
    ] = 10,
    tolerancia_erro: Annotated[
        int,
        typer.Option(
            "--tolerancia-erro",
            min=0,
            help="Falhas de validação consecutivas antes de abortar.",
        ),
    ] = 2,
    limite: Annotated[
        int | None,
        typer.Option("--limite", "-l", min=1, help="Processa no máximo N pendentes."),
    ] = None,
    lote_id: Annotated[
        str | None,
        typer.Option("--lote", help="Filtra as linhas por lote (coluna `lote`)."),
    ] = None,
    concorrencia: Annotated[
        int,
        typer.Option("--concorrencia", "-c", min=1, help="Chamadas simultâneas à LLM."),
    ] = 1,
    retentar_erros: Annotated[
        bool,
        typer.Option(
            "--retentar-erros",
            help="Reprocessa linhas cujo resultado anterior foi um erro.",
        ),
    ] = False,
    verboso: Annotated[
        bool,
        typer.Option(
            "--verboso", help="Mostra raciocínio e tool-calls de cada endereço."
        ),
    ] = False,
) -> None:
    """Processa em lote os endereços pendentes do dataset de etiquetagem."""
    config = carregar_config(env)
    console_llm = console if verboso else Console(quiet=True)

    # Valida o ambiente (CNEFE, municipios) uma vez, antes de começar o lote.
    Contexto.criar(config, console).fechar()

    conn = abrir_banco(banco)
    try:
        linhas = selecionar_pendentes(
            conn,
            limite=limite,
            lote=lote_id,
            incluir_erros=retentar_erros,
        )
        if not linhas:
            console.print("[yellow]Nenhum endereço pendente para processar.[/yellow]")
            return

        console.print(
            f"[bold]{len(linhas)}[/bold] endereço(s) a processar — modelo [bold]{config.api_model}[/bold], concorrência {concorrencia}."
        )
        inicio = time.perf_counter()
        resumo = executar_lote(
            conn,
            config,
            linhas,
            OpcoesLote(iteracoes, tolerancia_erro, concorrencia),
            console_llm=console_llm,
        )
        duracao = time.perf_counter() - inicio
    finally:
        conn.close()

    console.rule("Resumo")
    console.print(f"Sucesso: [green]{resumo.sucesso}[/green]")
    if resumo.erro:
        console.print(
            f"Erros: [yellow]{resumo.erro}[/yellow] (use --retentar-erros para reprocessar)"
        )
    console.print(f"Total: [bold]{resumo.total}[/bold] em {duracao:.1f}s")


if __name__ == "__main__":
    app()
