#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["markitdown", "requests"]
# ///

import markitdown
import os
import requests


API_KEY = os.environ.get("API_KEY")
API_URL = os.environ.get("API_URL")
API_MODEL = os.environ.get("API_MODEL")

if not API_MODEL or not API_MODEL or not API_URL:
    raise Exception(
        "As variáveis de ambiente API_MODEL, API_MODEL, API_URL devem ser fornecidas."
    )

tool = {
    "type": "function",
    "name": "responder",
    "description": "Responde ao solicitado",
    "parameters": {
        "type": "object",
        "properties": {
            "valor": {
                "type": "string",
                "description": "Valor da resposta",
            },
        },
        "required": ["valor"],
        "additionalProperties": False,
    },
    "strict": True,
}

response = requests.post(
    API_URL,
    headers={
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
    },
    json={
        "model": API_MODEL,
        "input": "quanto é 1+1? Use a ferramenta para responder.",
        "tools": [tool],
    },
)

data = response.json()
print(data)
