"""Nomes de municipios conhecidos (`municipios.csv`) como feature de lexico."""

from __future__ import annotations

import csv
from collections.abc import Iterable, Sequence
from functools import lru_cache
from pathlib import Path

from crf_endereco.config import MUNICIPIOS
from crf_endereco.features.texto import normalize, tokenize

# Trie dos nomes: cada nivel e uma palavra normalizada do nome. A chave
# sentinela `""` marca onde um nome termina, porque uns nomes sao prefixo de
# outros (`SANTA RITA` e `SANTA RITA DO PASSA QUATRO`), e nenhuma palavra
# normalizada e vazia.
type Trie = dict[str, Trie]
FIM = ""


def chave_nome(nome: str) -> tuple[str, ...]:
    """Palavras do nome normalizadas e sem pontuacao.

    `OLHO D'ÁGUA` vira `("OLHO", "D", "AGUA")`, a mesma chave que os tokens
    `OLHO`, `D`, `'`, `AGUA` do texto geram na comparacao.
    """
    return tuple(
        tok for tok in (normalize(t).upper() for t in tokenize(nome)) if tok.isalnum()
    )


def trie_de_nomes(nomes: Iterable[str]) -> Trie:
    """Trie das palavras dos nomes dados."""
    trie: Trie = {}
    for nome in nomes:
        chave = chave_nome(nome)
        if not chave:
            continue
        no = trie
        for palavra in chave:
            no = no.setdefault(palavra, {})
        no[FIM] = {}

    return trie


@lru_cache(maxsize=4)
def construir_trie(caminho: Path = MUNICIPIOS) -> Trie:
    """Le os nomes do CSV para um trie de palavras."""
    with caminho.open(newline="", encoding="utf-8") as arquivo:
        return trie_de_nomes(
            linha["municipio"] or "" for linha in csv.DictReader(arquivo)
        )


def marcar_nomes(
    sent: Sequence[str], trie: Trie, prefixo: str = "municipio"
) -> list[str | None]:
    """Marca cada token que faz parte de um nome do trie.

    Devolve `{prefixo}_B` no primeiro token do nome e `{prefixo}_I` nos seguintes
    (`None` fora de qualquer nome). So o nome completo casa: `SANTOS` sozinho
    nao marca `RUA SANTOS DUMONT`. A comparacao ignora pontuacao (`D'AGUA` casa
    como `D AGUA`) e, havendo sobreposicao, fica com o nome mais longo, para nao
    marcar `PASSA QUATRO` dentro de `SANTA RITA DO PASSA QUATRO`.
    """
    palavras = [
        (i, normalize(tok).upper()) for i, tok in enumerate(sent) if tok.isalnum()
    ]
    marcas: list[str | None] = [None] * len(sent)

    for inicio, (pos, _) in enumerate(palavras):
        # Token ja pertence a um nome casado a partir de uma posicao anterior
        if marcas[pos] is not None:
            continue

        no = trie
        fim: int | None = None
        for k in range(inicio, len(palavras)):
            proximo = no.get(palavras[k][1])
            if proximo is None:
                break
            no = proximo
            if FIM in no:
                fim = k + 1

        if fim is None:
            continue

        marcas[pos] = f"{prefixo}_B"
        for pos_interna, _ in palavras[inicio + 1 : fim]:
            marcas[pos_interna] = f"{prefixo}_I"

    return marcas


def marcar_municipios(sent: Sequence[str], trie: Trie) -> list[str | None]:
    """Marca os tokens que fazem parte de um nome de municipio conhecido."""
    return marcar_nomes(sent, trie, "municipio")
