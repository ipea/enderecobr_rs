"""Gera `src/data/municipios_ambiguidade.csv` a partir do CNEFE.

Para que serve: separar o lexico de municipios em nomes que praticamente so
aparecem como municipio (`ANAPOLIS`: 2 municipios tem localidade com esse nome)
dos que sao nome comum de bairro (`BOA VISTA`: 1492, `SANTA LUZIA`: 569). A
saida alimenta a feature `municipio_unico`/`municipio_ambiguo` e a view
`municipio_ambiguidade` da ferramenta de SQL da anotacao.

O CSV e pequeno (uma linha por municipio) e fica versionado junto do
`municipios.csv`; regenerar quando o CNEFE mudar de versao:

    uv run python scripts/gerar_ambiguidade_municipios.py
"""

from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path

import duckdb

from crf_endereco.config import AMBIGUIDADE_MUNICIPIOS, CAMINHO_CNEFE, MUNICIPIOS
from crf_endereco.features.municipios import chave_nome

# Nome com menos que isso casa com qualquer coisa e nao ajuda a decidir nada.
TAMANHO_MINIMO = 4


def contar(caminho: Path = CAMINHO_CNEFE) -> dict[str, int]:
    """Municipios distintos que tem uma localidade com cada nome."""
    con = duckdb.connect()
    try:
        _ = con.execute("set memory_limit='4GB'")
        linhas = con.execute(
            "select upper(strip_accents(trim(desc_localidade))) as nome, "
            "count(distinct code_muni) as n_localidades "
            "from read_parquet(?) "
            "where desc_localidade is not null "
            "  and length(trim(desc_localidade)) >= ? "
            "group by 1",
            [str(caminho), TAMANHO_MINIMO],
        ).fetchall()
    finally:
        con.close()

    # Varias grafias podem cair na mesma chave normalizada; o maior valor evita
    # subestimar a ambiguidade de um nome escrito de formas diferentes.
    contagem: dict[str, int] = defaultdict(int)
    for nome, n_localidades in linhas:
        chave = " ".join(chave_nome(str(nome)))
        if chave:
            contagem[chave] = max(contagem[chave], int(n_localidades))
    return dict(contagem)


def gravar(
    contagem: dict[str, int],
    destino: Path = AMBIGUIDADE_MUNICIPIOS,
    municipios: Path = MUNICIPIOS,
) -> int:
    """Grava uma linha por municipio com o n_localidades do seu nome."""
    with municipios.open(newline="", encoding="utf-8") as arquivo:
        linhas = list(csv.DictReader(arquivo))
    destino.parent.mkdir(parents=True, exist_ok=True)
    with destino.open("w", newline="", encoding="utf-8") as arquivo:
        escritor = csv.writer(arquivo)
        _ = escritor.writerow(["cod_ibge", "municipio", "n_localidades"])
        for linha in linhas:
            nome = linha["municipio"] or ""
            chave = " ".join(chave_nome(nome))
            # Nome que nunca aparece como localidade no CNEFE e inequivoco.
            _ = escritor.writerow([linha["cod_ibge"], nome, contagem.get(chave, 0)])
    return len(linhas)


def main() -> None:
    contagem = contar()
    total = gravar(contagem)
    print(f"{total} municipios gravados em {AMBIGUIDADE_MUNICIPIOS}")


if __name__ == "__main__":
    main()
