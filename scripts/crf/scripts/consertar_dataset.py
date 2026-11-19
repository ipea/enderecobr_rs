"""Corrige o texto colado e os rotulos que a regra escrita do prompt ja mandava.

Tres consertos, todos verificaveis contra o prompt do anotador:

1. Texto colado na base de origem (`CARAMURUANTIGA`): quando dois segmentos se
   encostam sem separador e os dois lados sao alfanumericos, o campo original foi
   concatenado sem espaco. Insere o espaco, o que faz os tokens casarem com a
   anotacao e devolve a linha ao treino.
2. `POV <nome>` rotulado como logradouro/localidade -> `nucleo_rural` (cabeca +
   nome de lugar rural). `POV` sozinho continua `ruido`.
3. `ESCOLA` sozinho (sem nome) rotulado como complemento/outros -> `ruido`: e
   rotulo de campo vazado e nao ha nome de estabelecimento no texto.

Como o dataset cresce por anotacao, os dois consertos voltam a aparecer em lote
novo: rode sem `--aplicar` para ver o que mudaria, depois com.

Uso: uv run python scripts/consertar_dataset.py [--aplicar]
"""

import json
import shutil
import sqlite3
import sys
from datetime import UTC, datetime

from crf_endereco.config import CAMINHO_DATASET
from crf_endereco.dataset import calcular_hash
from crf_endereco.features import tokenize

BANCO = CAMINHO_DATASET


def espacos_faltando(endereco: str, segmentos: list[dict[str, str]]) -> list[int]:
    """Posicoes onde dois segmentos se encostam sem separador entre eles."""
    posicoes: list[int] = []
    ultima = 0
    for segmento in segmentos:
        valor = segmento.get("valor", "")
        if not valor:
            continue
        posicao = endereco.find(valor, ultima)
        if posicao < 0:
            continue
        if posicao > 0 and posicao == ultima and endereco[posicao - 1].isalnum():
            posicoes.append(posicao)
        ultima = posicao + len(valor)
    return posicoes


def consertar_texto(endereco: str, posicoes: list[int]) -> str:
    pedacos = []
    anterior = 0
    for posicao in posicoes:
        pedacos.append(endereco[anterior:posicao])
        pedacos.append(" ")
        anterior = posicao
    pedacos.append(endereco[anterior:])
    return "".join(pedacos)


def ajustar(segmentos: list[dict[str, str]]) -> tuple[list[dict[str, str]], list[str]]:
    """Rótulos corrigidos e o que mudou (para o relatorio)."""
    mudancas: list[str] = []
    novos: list[dict[str, str]] = []
    for segmento in segmentos:
        tipo = segmento.get("tipo", "")
        valor = segmento.get("valor", "").strip()
        cabeca = valor.upper().split()[0] if valor else ""
        novo = tipo
        if cabeca == "POV" and len(valor.split()) > 1 and tipo != "nucleo_rural":
            novo = "nucleo_rural"
        elif valor.upper() == "ESCOLA" and tipo != "ruido":
            novo = "ruido"
        if novo != tipo:
            mudancas.append(f"{tipo} -> {novo}: {valor!r}")
            segmento = {**segmento, "tipo": novo}
        novos.append(segmento)
    return novos, mudancas


def main() -> None:
    aplicar = "--aplicar" in sys.argv
    conn = sqlite3.connect(BANCO)
    linhas = conn.execute(
        "SELECT id, endereco, resposta_llm, hash_endereco FROM enderecos "
        "WHERE resposta_llm IS NOT NULL"
    ).fetchall()

    hashes = {h for (h,) in conn.execute("SELECT hash_endereco FROM enderecos")}
    texto, rotulo = [], []
    for id_linha, endereco, bruto, _hash in linhas:
        try:
            resposta = json.loads(bruto)
        except json.JSONDecodeError:
            continue
        segmentos = resposta.get("segmentos")
        if not isinstance(segmentos, list):
            continue

        novo_endereco = endereco
        posicoes = espacos_faltando(endereco, segmentos)
        if posicoes:
            candidato = consertar_texto(endereco, posicoes)
            # So vale mexer no texto quando o espaco muda a tokenizacao: sem isso
            # a linha ja treina certo e o conserto seria so cosmetico.
            if tokenize(candidato) != tokenize(endereco):
                novo_endereco = candidato
                texto.append((id_linha, endereco, novo_endereco, len(posicoes)))

        novos, mudancas = ajustar(segmentos)
        if mudancas:
            resposta["segmentos"] = novos
            rotulo.append((id_linha, novo_endereco, json.dumps(resposta, ensure_ascii=False), mudancas))

    print(f"== texto: {len(texto)} enderecos com palavra colada ==")
    for item in texto:
        print(f"  [{item[0]}] {item[1][:60]!r}\n        -> {item[2][:60]!r} ({item[3]} espaco(s))")
    print(f"\n== rotulos: {len(rotulo)} enderecos ==")
    for item in rotulo:
        for mudanca in item[3]:
            print(f"  [{item[0]}] {mudanca}")

    colisoes = [
        novo for _, _, novo, _ in texto if calcular_hash(novo) in hashes
    ]
    if colisoes:
        print(f"\nABORTADO: {len(colisoes)} endereco(s) consertado(s) ja existem no banco")
        return

    if not aplicar:
        print("\n(seco: rode com --aplicar para gravar)")
        return

    backup = BANCO.with_name(f"{BANCO.name}.bak-{datetime.now(UTC):%Y%m%d-%H%M%S}")
    shutil.copy2(BANCO, backup)
    print(f"\nbackup: {backup}")

    with conn:
        for id_linha, _, novo_endereco, _ in texto:
            conn.execute(
                "UPDATE enderecos SET endereco = ?, hash_endereco = ? WHERE id = ?",
                (novo_endereco, calcular_hash(novo_endereco), id_linha),
            )
        for id_linha, _, novo_json, _ in rotulo:
            conn.execute(
                "UPDATE enderecos SET resposta_llm = ? WHERE id = ?",
                (novo_json, id_linha),
            )
    print(f"gravado: {len(texto)} enderecos, {len(rotulo)} respostas")


if __name__ == "__main__":
    main()
