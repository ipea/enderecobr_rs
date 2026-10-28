"""Sorteio de uma amostra diversa dentro da base de origem."""

from __future__ import annotations

import random
from collections.abc import Callable, Iterator
from dataclasses import dataclass

import duckdb
from tqdm import tqdm

from crf_endereco.anotacao.populacao.populador import FiltroDiversidade, Populador
from crf_endereco.registro import Registro


@dataclass
class ResultadoAmostragem:
    amostra: list[Registro]
    candidatos: int
    aceitos: int


def reservatorio(
    fonte: Iterator[Registro],
    tamanho: int,
    seed: int | None,
) -> list[Registro]:
    """Reservoir sampling (Algoritmo R): amostra uniforme de `tamanho`.

    Um único passe e memória constante (`tamanho` registros), independente do
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


def amostrar_diverso(
    populador: Populador,
    criar_filtro: Callable[[], FiltroDiversidade],
    *,
    tamanho: int,
    seed: int | None,
    fator_inicial: int = 3,
    max_rodadas: int = 2,
) -> ResultadoAmostragem:
    """Amostra `tamanho` endereços diversos, repetindo até atingir o pedido.

    Cada rodada faz um reservoir de `tamanho * fator` candidatos (uma leitura
    da origem) e aplica o filtro de diversidade sobre esse pool, **parando
    assim que `tamanho` forem aceitos**. O pool é limitado de propósito (o
    filtro fuzzy custa O(aceitos) por candidato, então passar o filtro na
    origem inteira seria inviável) e só é ampliado (dobrado) quando o pool
    inteiro não bastou para atingir o pedido.

    O pool é embaralhado antes do filtro: o reservoir mantém os `tamanho`
    primeiros na ordem da origem, então parar cedo nesse prefixo enviesaria a
    amostra pela posição no arquivo (na ANEEL/parquet, clusterização
    geográfica).
    """
    fator = fator_inicial
    candidatos = 0
    aceitos = 0
    amostra: list[Registro] = []
    rnd = random.Random(seed)

    for _ in range(max_rodadas):
        conn = duckdb.connect()
        try:
            pool = reservatorio(populador.popular(conn), tamanho * fator, seed)
        finally:
            conn.close()

        rnd.shuffle(pool)
        filtro = criar_filtro()
        examinados = 0
        amostra = []
        for registro in tqdm(pool, total=len(pool)):
            examinados += 1
            if filtro.aceitar(registro.endereco):
                amostra.append(registro)
                if len(amostra) >= tamanho:
                    break
        candidatos, aceitos = examinados, len(amostra)

        if aceitos >= tamanho:
            break
        fator *= 2

    return ResultadoAmostragem(amostra[:tamanho], candidatos, aceitos)
