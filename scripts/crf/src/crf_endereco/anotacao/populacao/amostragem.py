"""Sorteio de uma amostra diversa dentro da base de origem."""

from __future__ import annotations

import random
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path

import duckdb
from rapidfuzz import fuzz, process
from tqdm import tqdm

from crf_endereco.anotacao.populacao.populador import Fonte, ler
from crf_endereco.registro import Registro


@dataclass
class Resultado:
    """Amostra aceita e o tamanho do pool examinado."""

    amostra: list[Registro]
    candidatos: int
    aceitos: int


def reservatorio(
    fonte: Iterator[Registro],
    tamanho: int,
    seed: int | None,
) -> list[Registro]:
    """Reservoir sampling (Algoritmo R): amostra uniforme de `tamanho`.

    Um unico passe e memoria constante (`tamanho` registros), independente do
    tamanho da origem.
    """
    rnd = random.Random(seed)
    reserva: list[Registro] = []

    for i, registro in enumerate(fonte):
        if i < tamanho:
            reserva.append(registro)
        else:
            # Troca com probabilidade tamanho / (i + 1).
            escolhido = rnd.randrange(i + 1)
            if escolhido < tamanho:
                reserva[escolhido] = registro

    return reserva


def _aceitar(
    endereco: str, aceitos: Sequence[str], similaridade_maxima: float | None
) -> bool:
    """False quando `endereco` e parecido demais com um ja aceito (rapidfuzz)."""
    if similaridade_maxima is None:
        return True
    # `score_cutoff` corta cedo: so interessa um match >= limite.
    return not process.extractOne(
        endereco,
        aceitos,
        scorer=fuzz.token_sort_ratio,
        score_cutoff=similaridade_maxima,
    )


def amostrar_diverso(
    fonte: Fonte,
    arquivo: Path,
    *,
    tamanho: int,
    seed: int | None,
    similaridade_maxima: float | None = None,
    existentes: Sequence[str] = (),
    aba: str | None = None,
    max_rodadas: int = 2,
) -> Resultado:
    """Amostra `tamanho` enderecos diversos, repetindo ate atingir o pedido.

    Cada rodada faz um reservoir de `tamanho * fator` candidatos (uma leitura da
    origem) e aplica o filtro de diversidade sobre esse pool, **parando assim que
    `tamanho` forem aceitos**. O pool e limitado de proposito (o filtro fuzzy
    custa O(aceitos) por candidato, entao passar o filtro na origem inteira seria
    inviavel) e so e ampliado (dobrado) quando o pool inteiro nao bastou.

    O pool e embaralhado antes do filtro: o reservoir mantem os `tamanho`
    primeiros na ordem da origem, entao parar cedo nesse prefixo enviesaria a
    amostra pela posicao no arquivo (na ANEEL/parquet, clusterizacao geografica).
    """
    # Sem filtro nao ha descarte: o pool ja e o tamanho final.
    fator = 1 if similaridade_maxima is None else 3
    candidatos = 0
    aceitos = 0
    amostra: list[Registro] = []
    rnd = random.Random(seed)

    for _ in range(max_rodadas):
        conn = duckdb.connect()
        try:
            pool = reservatorio(ler(conn, fonte, arquivo, aba), tamanho * fator, seed)
        finally:
            conn.close()

        rnd.shuffle(pool)
        comparados: list[str] = list(existentes)
        examinados = 0
        amostra = []
        for registro in tqdm(pool, total=len(pool)):
            examinados += 1
            if _aceitar(registro.endereco, comparados, similaridade_maxima):
                comparados.append(registro.endereco)
                amostra.append(registro)
                if len(amostra) >= tamanho:
                    break
        candidatos, aceitos = examinados, len(amostra)

        if aceitos >= tamanho:
            break
        fator *= 2

    return Resultado(amostra=amostra[:tamanho], candidatos=candidatos, aceitos=aceitos)
