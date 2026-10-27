"""Estratos de pendentes e a ponderacao entre eles."""
import math
from dataclasses import dataclass


@dataclass(frozen=True)
class EstratoPendente:
    """Um estrato de amostragem com pendentes (uma origem ou uma UF).

    `chave` identifica o estrato (nome da origem, ou sigla da UF); `anotados`
    conta as anotações bem-sucedidas (sem `$.erro`) do estrato — base do peso
    1/(anotados+1) — e `pendentes` limita a cota.
    """

    chave: str
    anotados: int
    pendentes: int

@dataclass(frozen=True)
class LinhaPendente:
    """Uma linha ainda não processada do dataset de etiquetagem."""

    id: int
    endereco: str
    extras: str

def alocar(
    estratos: list[EstratoPendente], tamanho: int
) -> list[tuple[EstratoPendente, int]]:
    """Distribui `tamanho` entre os estratos proporcional ao peso 1/(anotados+1).

    Método do maior resto, respeitando os pendentes de cada estrato (o
    excedente de um estrato saturado é repassado aos demais). Retorna só as
    cotas > 0. Serve tanto às origens quanto às UFs (balanceamento hierárquico).
    """
    if tamanho <= 0 or not estratos:
        return []
    pesos = {e.chave: 1.0 / (e.anotados + 1) for e in estratos}
    total_peso = sum(pesos.values())
    cotas = {e.chave: tamanho * pesos[e.chave] / total_peso for e in estratos}
    cota = {e.chave: min(math.floor(cotas[e.chave]), e.pendentes) for e in estratos}
    restante = tamanho - sum(cota.values())
    ordem = sorted(
        estratos,
        key=lambda e: (cotas[e.chave] - math.floor(cotas[e.chave]), pesos[e.chave]),
        reverse=True,
    )
    while restante > 0 and any(cota[e.chave] < e.pendentes for e in estratos):
        for e in ordem:
            if restante <= 0:
                break
            if cota[e.chave] < e.pendentes:
                cota[e.chave] += 1
                restante -= 1
    return [(e, cota[e.chave]) for e in estratos if cota[e.chave] > 0]
