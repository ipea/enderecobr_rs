"""Marca linhas para re-anotacao: guarda a anotacao atual e vira erro.

A fila de re-anotacao e a mesma dos erros: a anotacao atual vai para
`resposta_llm_antiga` e `resposta_llm` recebe `{"erro": ...}`. As linhas ganham
`lote = reanotacao` (o lote original fica em `meta.lote_original`), entao

    crf etiquetar lote <banco> --apenas-erros --lote reanotacao

reprocessa exatamente elas, sem varrer os erros antigos de outras origens. O
dataset de treino ignorara essas linhas enquanto estiverem marcadas.

Entrada: JSONL com `{"id": ..., "motivo": ...}` (uma linha por registro).

    uv run python scripts/marcar_reanotacao.py /tmp/amostra.jsonl
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

from crf_endereco.config import CAMINHO_DATASET

LOTE_REANOTACAO = "reanotacao"

# A anotacao atual so vira backup quando ainda nao e um erro: reexecutar o
# script nao pode apagar o backup com a propria marca.
def marcar(caminho: Path, linhas: list[dict[str, str]]) -> int:
    conn = sqlite3.connect(str(caminho))
    try:
        total = 0
        for linha in linhas:
            marca = json.dumps({"erro": f"reanotacao: {linha.get('motivo', '')}"})
            cur = conn.execute(
                "update enderecos "
                "set resposta_llm_antiga = case "
                "        when json_extract(resposta_llm, '$.erro') is null "
                "        then resposta_llm else resposta_llm_antiga end, "
                "    resposta_llm = ?, "
                "    meta = json_set(coalesce(nullif(meta, ''), '{}'), "
                "                    '$.lote_original', lote), "
                "    lote = ? "
                "where id = ?",
                (marca, LOTE_REANOTACAO, int(linha["id"])),
            )
            total += cur.rowcount
        conn.commit()
        return total
    finally:
        conn.close()


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("uso: marcar_reanotacao.py ARQUIVO.jsonl")
    origem = Path(sys.argv[1])
    if not origem.is_file():
        raise SystemExit(f"arquivo nao encontrado: {origem}")
    try:
        texto_jsonl = origem.read_text(encoding="utf-8")
        linhas = [
            json.loads(linha) for linha in texto_jsonl.splitlines() if linha.strip()
        ]
    except OSError as erro:
        raise SystemExit(f"nao consegui ler {origem}: {erro}") from erro
    except json.JSONDecodeError as erro:
        raise SystemExit(f"JSONL invalido em {origem}: {erro}") from erro
    total = marcar(CAMINHO_DATASET, linhas)
    print(f"{total} linhas marcadas para re-anotacao ({len(linhas)} pedidas)")


if __name__ == "__main__":
    main()
