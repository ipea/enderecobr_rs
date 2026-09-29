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

if not API_KEY or not API_MODEL or not API_URL:
    raise Exception(
        "As variáveis de ambiente API_MODEL, API_MODEL, API_URL devem ser fornecidas."
    )

tool = {
    "type": "function",
    "function": {
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
    },
}

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
                "content": "Quanto é 1+1? Use a ferramenta `responder`.",
            }
        ],
        "tools": [tool],
    },
)

data = response.json()
print(data)
