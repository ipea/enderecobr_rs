#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["markitdown", "requests"]
# ///

import markitdown
import os
import json
import requests


API_KEY = os.environ.get("API_KEY")
API_URL = os.environ.get("API_URL")
API_MODEL = os.environ.get("API_MODEL")
SEARX_URL = os.environ.get("SEARX_URL")

if not API_KEY or not API_MODEL or not API_URL:
    raise Exception(
        "As variáveis de ambiente API_MODEL, API_MODEL, API_URL devem ser fornecidas."
    )

if not SEARX_URL:
    print(
        "Atenção: A variável SEARX_URL não foi definida, a ferramenta de busca web não estará disponível."
    )


def renderizar_prompt(n_rodadas: int, endereco: str, extras: str):
    return f"""Me ajude a segmentar endereços brasileiros para que eu seja capaz de realizar uma geolocalização posteriormente e treinar um modelo de CRF em cima deste dado.

Use as ferramentas que você tem acesso para auxiliar na sua resposta. Para casos simples, você pode dar a resposta diretamente.
Quando tiver tomado uma decisão, use a ferramenta `responder`.
Copie os campos de forma verbatim como está no valor bruto. Não normalize, nem expanda abreviações etc.
Use o campo de comentário livre para fazer obervações sobre seus achados, quando buscar informações externas ou ficar em dúvida. Você não deve usa-lo para explicar coisas óbvias.
Se um campo não aparece no endereço, deixe-o vazio. Não enriqueça os dados se algo não existir. Não valide-o também, se os campos estão claros o suficiente, você já deve responder, mesmo que você não conheça o endereço.

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


response = requests.post(
    f"{API_URL}/v1/chat/completions",
    headers={
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
    },
    json={
        "model": API_MODEL,
        "messages": [
            {
                "role": "user",
                "content": renderizar_prompt(
                    10,
                    "r das rosas, 192 apt 103",
                    "N/A",
                ),
            }
        ],
        "tools": criar_ferramentas(),
    },
)

data = response.json()
print(json.dumps(data, indent=4))
