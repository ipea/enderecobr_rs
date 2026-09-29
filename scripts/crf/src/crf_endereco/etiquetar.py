#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["markitdown[pdf,docx,xls,xlsx]", "requests", "duckdb"]
# ///

import json
import os
from dataclasses import dataclass
from pprint import pprint
from typing import Any

import duckdb
import markitdown
import requests

API_KEY = os.environ.get("API_KEY")
API_URL = os.environ.get("API_URL")
API_MODEL = os.environ.get("API_MODEL")
SEARX_URL = os.environ.get("SEARX_URL")
CNEFE_PATH = os.environ.get("CNEFE_PATH")
MUNICIPIOS_PATH = "../../src/data/municipios.csv"

md = markitdown.MarkItDown()

if not API_KEY or not API_MODEL or not API_URL:
    raise Exception(
        "As variáveis de ambiente API_MODEL, API_MODEL, API_URL devem ser fornecidas."
    )

if not SEARX_URL:
    print(
        "Atenção: A variável SEARX_URL não foi definida, a ferramenta de busca web não estará disponível."
    )


def renderizar_prompt(n_rodadas: int, endereco: str, extras: str):
    return f"""Me ajude a segmentar endereços brasileiros para que eu seja capaz de treinar um modelo de CRF em cima deste dado.

Use as ferramentas que você tem acesso para auxiliar na sua resposta. Para casos simples, você pode dar a resposta diretamente.
Quando tiver tomado uma decisão, use a ferramenta `responder`.
Copie os campos de forma verbatim como está no valor bruto. Não normalize, nem expanda abreviações etc.
Use o campo de comentário livre para fazer obervações sobre seus achados, quando buscar informações externas ou ficar em dúvida. Você não deve usa-lo para explicar coisas óbvias.
Se um campo não aparece no endereço, deixe-o vazio. Não enriqueça os dados se algo não existir. Não valide-o também, se os campos estão claros o suficiente, você já deve responder, mesmo que você não conheça o endereço.

## Schema do CNEFE:

Os dados parecem estar todos em maiúsculo. Procure limitar por municipio e/ou uf suas consultas, além de usar sempre um LIMIT.

### Tabela 'cnefe':

column_name|column_type|null|key|default|extra
-------------
code_address|INTEGER|YES|NULL|NULL|NULL
code_state|INTEGER|YES|NULL|NULL|NULL
code_muni|INTEGER|YES|NULL|NULL|NULL
code_district|INTEGER|YES|NULL|NULL|NULL
code_sub_district|BIGINT|YES|NULL|NULL|NULL
code_sector|VARCHAR|YES|NULL|NULL|NULL
num_quadra|INTEGER|YES|NULL|NULL|NULL
num_face|INTEGER|YES|NULL|NULL|NULL
cep|INTEGER|YES|NULL|NULL|NULL
desc_localidade|VARCHAR|YES|NULL|NULL|NULL
nom_tipo_seglogr|VARCHAR|YES|NULL|NULL|NULL
nom_titulo_seglogr|VARCHAR|YES|NULL|NULL|NULL
nom_seglogr|VARCHAR|YES|NULL|NULL|NULL
num_adress|INTEGER|YES|NULL|NULL|NULL
dsc_modificador|VARCHAR|YES|NULL|NULL|NULL
nom_comp_elem1|VARCHAR|YES|NULL|NULL|NULL
val_comp_elem1|VARCHAR|YES|NULL|NULL|NULL
nom_comp_elem2|VARCHAR|YES|NULL|NULL|NULL
val_comp_elem2|VARCHAR|YES|NULL|NULL|NULL
nom_comp_elem3|VARCHAR|YES|NULL|NULL|NULL
val_comp_elem3|VARCHAR|YES|NULL|NULL|NULL
nom_comp_elem4|VARCHAR|YES|NULL|NULL|NULL
val_comp_elem4|VARCHAR|YES|NULL|NULL|NULL
nom_comp_elem5|VARCHAR|YES|NULL|NULL|NULL
val_comp_elem5|VARCHAR|YES|NULL|NULL|NULL
lat|DOUBLE|YES|NULL|NULL|NULL
lon|DOUBLE|YES|NULL|NULL|NULL
nv_geo_coord|INTEGER|YES|NULL|NULL|NULL
cod_especie|INTEGER|YES|NULL|NULL|NULL
dsc_estabelecimento|VARCHAR|YES|NULL|NULL|NULL
cod_indicador_estab_endereco|INTEGER|YES|NULL|NULL|NULL
cod_indicador_const_endereco|INTEGER|YES|NULL|NULL|NULL
cod_indicador_finalidade_const|INTEGER|YES|NULL|NULL|NULL
cod_tipo_especi|INTEGER|YES|NULL|NULL|NULL

### Tabela 'municipio':
column_name|column_type|null|key|default|extra
-------------
cod_ibge|BIGINT|YES|NULL|NULL|NULL
municipio|VARCHAR|YES|NULL|NULL|NULL
uf|VARCHAR|YES|NULL|NULL|NULL

### Tabela de refência de Estados (não está no banco):

| codigo | nome |
|---|---|---|
| 11 | RONDONIA |
| 12 | ACRE |
| 13 | AMAZONAS |
| 14 | RORAIMA |
| 15 | PARA |
| 16 | AMAPA |
| 17 | TOCANTINS |
| 21 | MARANHAO |
| 22 | PIAUI |
| 23 | CEARA |
| 24 | RIO GRANDE DO NORTE |
| 25 | PARAIBA |
| 26 | PERNAMBUCO |
| 27 | ALAGOAS |
| 28 | SERGIPE |
| 29 | BAHIA |
| 31 | MINAS GERAIS |
| 32 | ESPIRITO SANTO |
| 33 | RIO DE JANEIRO |
| 35 | SAO PAULO |
| 41 | PARANA |
| 42 | SANTA CATARINA |
| 43 | RIO GRANDE DO SUL |
| 50 | MATO GROSSO DO SUL |
| 51 | MATO GROSSO |
| 52 | GOIAS |
| 53 | DISTRITO FEDERAL |

Você tem {n_rodadas} rodadas para responder.

Endereço desejado: {endereco}

Informações extras:
{extras}
"""


def criar_ferramentas():
    tools = []

    tools.append(
        {
            "type": "function",
            "function": {
                "name": "responder",
                "description": "Dá a resposta final da solicitação",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "logradouro": {
                            "type": "string",
                        },
                        "numero": {
                            "type": "string",
                        },
                        "complemento": {
                            "type": "string",
                        },
                        "localidade": {
                            "type": "string",
                        },
                        "cep": {
                            "type": "string",
                        },
                        "municipio": {
                            "type": "string",
                        },
                        "uf": {
                            "type": "string",
                        },
                        "observacoes": {
                            "type": "string",
                        },
                    },
                    "required": [],
                    "additionalProperties": False,
                },
                "strict": True,
            },
        }
    )

    tools.append(
        {
            "type": "function",
            "function": {
                "name": "acessar_url",
                "description": "Acessa a URL solicitada e retorna o resultado usando a lib markitdown",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "url": {
                            "type": "string",
                            "description": "URL desejada",
                        },
                    },
                    "required": ["valor"],
                    "additionalProperties": False,
                },
                "strict": True,
            },
        }
    )

    tools.append(
        {
            "type": "function",
            "function": {
                "name": "consulta_sql",
                "description": "Realiza uma consulta SQL usando o DuckDB em cima do CNEFE.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "sql": {
                            "type": "string",
                            "description": "SQL a ser executado",
                        },
                    },
                    "required": ["sql"],
                    "additionalProperties": False,
                },
                "strict": True,
            },
        }
    )

    if SEARX_URL:
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": "buscar",
                    "description": "Realizar uma busca em vários motores de busca.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "Query de busca",
                            },
                        },
                        "required": ["query"],
                        "additionalProperties": False,
                    },
                    "strict": True,
                },
            }
        )
    return tools


def iniciar_duckbd():
    query = f"""
CREATE VIEW IF NOT EXISTS cnefe AS SELECT * FROM read_parquet("{CNEFE_PATH}");
CREATE VIEW IF NOT EXISTS municipio AS SELECT * FROM read_csv("{MUNICIPIOS_PATH}");
"""
    conn = duckdb.connect("/tmp/cnefe-enderecobr.db")
    _ = conn.execute(query)

    return conn


conn = iniciar_duckbd()


def buscar(query: str):
    params = {"q": query, "format": "json"}
    try:
        res = requests.get(f"{SEARX_URL}", params=params)
        resposta_bruta = res.json()
    except Exception as e:
        return f"Ocorreu um erro ao buscar por '{query}': {e!s}"

    resposta_final = []
    for result in resposta_bruta.get("results", []):
        titulo = result.get("title", "")
        conteudo = result.get("content", "")
        url = result.get("url", "")
        engines = result.get("engines", [])
        pubdate = result.get("pubdate", [])  # Data formatada

        atual = f"""# {titulo}
url: {url}
motores de busca: {", ".join(engines)}
data publicação: {pubdate}
conteúdo: {conteudo}

"""
        resposta_final.append(atual)

    return "\n".join(resposta_final)


def acessar_url(url: str):
    try:
        res = requests.get(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:156.0) Gecko/20100101 Firefox/156.0"
            },
        )
        return str(md.convert(res).markdown)
    except Exception as e:
        return f"Ocorreu um erro ao acessar '{url}': {e!s}"


def consulta_sql(sql: str):
    try:
        consulta = conn.execute(sql)
        colunas = [str(col[0]) for col in consulta.description]
        resultado = consulta.fetchall()
    except Exception as e:
        return f"Ocorreu um erro ao realizar a consulta: {e!s}"

    corpo_tabela = "\n".join(["|".join([str(e) for e in linha]) for linha in resultado])

    return f"""{"|".join(colunas)}
---------
{corpo_tabela}
"""


@dataclass()
class ToolCall:
    idx: str
    nome: str
    argumentos: Any


@dataclass()
class RespostaFinal:
    logradouro: str
    numero: str
    complemento: str
    localidade: str
    cep: str
    municipio: str
    uf: str
    observacoes: str


@dataclass()
class RespostaModelo:
    resposta: str
    raciociono: str
    tool_calls: list[ToolCall]
    message_original: Any

    def obter_resposta_final(self):
        return next(iter([c for c in self.tool_calls if c.nome == "responder"]), None)


def estruturar_ferramentas(bruto):
    chamadas_ferramentas = bruto.get("tool_calls", [])
    resultado: list[ToolCall] = []
    for call in chamadas_ferramentas:
        idx = call.get("id", "")
        fun = call.get("function", {})
        nome: str = fun.get("name", "")
        args_bruto = fun.get("arguments")
        args = json.loads(args_bruto)

        resultado.append(ToolCall(idx, nome, args))
    return resultado


def estruturar_resposta_modelo(resposta_bruta) -> RespostaModelo:
    msg_modelo = resposta_bruta.get("choices", [{}])[0].get("message", {})

    resposta = msg_modelo.get("content")
    raciociono = msg_modelo.get("reasoning", "")
    calls = estruturar_ferramentas(msg_modelo)

    return RespostaModelo(resposta, raciociono, calls, msg_modelo)


def despachar_ferramenta(call: ToolCall):
    match call.nome:
        case "buscar":
            return buscar(call.argumentos.get("query"))
        case "consulta_sql":
            return consulta_sql(call.argumentos.get("sql"))
        case "acessar_url":
            return acessar_url(call.argumentos.get("url"))

    return f"Ferramenta {call.nome} solicitada não existe"


def processar_resultado_final(resposta: ToolCall) -> RespostaFinal | str:

    logradouro = resposta.argumentos.get("logradouro")
    numero = resposta.argumentos.get("numero")
    complemento = resposta.argumentos.get("complemento")
    localidade = resposta.argumentos.get("localidade")
    cep = resposta.argumentos.get("cep")
    municipio = resposta.argumentos.get("municipio")
    uf = resposta.argumentos.get("uf")
    observacoes = resposta.argumentos.get("observacoes")

    return RespostaFinal(
        logradouro=logradouro,
        numero=numero,
        complemento=complemento,
        localidade=localidade,
        cep=cep,
        municipio=municipio,
        uf=uf,
        observacoes=observacoes,
    )


def realizar_requisicao(messages):
    response = requests.post(
        f"{API_URL}/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": API_MODEL,
            "messages": messages,
            "tools": criar_ferramentas(),
            "temperature": 0.6,
        },
    )

    response.raise_for_status()
    data = response.json()
    return data


def react_loop(n_iter: int = 10):
    messages = [
        {
            "role": "user",
            "content": renderizar_prompt(
                n_iter,
                "FAZ ÁREA DE TERRA SITUADA NO LUGAR DENOMINADO BARRA DO BEBEDOURO 0 BARRA DO BEBEDOURO",
                "Municipio: Petrolina/PE\nLocalidade: ZONA RURAL\nBanco de Dados: Imóveis da União",
            ),
        }
    ]

    for i in range(n_iter):
        resposta_bruta = realizar_requisicao(messages)
        resposta = estruturar_resposta_modelo(resposta_bruta)

        messages.append(resposta.message_original)

        print("========================")
        print(f"# Raciociono:\n{resposta.raciociono}")
        print("========================")
        print()
        print(resposta.resposta)

        resposta_final = resposta.obter_resposta_final()

        if resposta_final:
            resultado_final = processar_resultado_final(resposta_final)
            print()
            pprint(resultado_final)
            break

        if not resposta_final:
            for c in resposta.tool_calls:
                pprint(c)
                resposta_ferramenta = despachar_ferramenta(c)
                print()
                print(resposta_ferramenta)

                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": c.idx,
                        "content": resposta_ferramenta,
                    }
                )

        if i == n_iter - 1:
            print("ÚLTIMA ITERACAO")
            messages.append(
                {
                    "role": "user",
                    "content": "Última iteração - Dê sua resposta agora ou se abstenha",
                }
            )

    print(json.dumps(resposta_bruta, indent=4))


react_loop()
