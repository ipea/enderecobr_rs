"""Filtros dos pendentes pelas previsoes e probabilidades do CRF."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import cast

import sklearn_crfsuite
import typer

from crf_endereco.anotacao.ontologia import TIPOS_SEGMENTO
from crf_endereco.anotacao.pendentes import Pendente
from crf_endereco.config import CAMINHO_TAGGER
from crf_endereco.features import ExtratorFeature, tokenize
from crf_endereco.modelo.crf import carregar_tagger
from crf_endereco.rotulos import mapa_tipo_segmento
from crf_endereco.segmentador_rust import rodar_segmentacao
from crf_endereco.ui import progresso

# Rotulos que o CRF consegue emitir: espelham `TipoSegmento::TODOS` do Rust.
# Derivados do proprio mapa: o que o treino colapsa em `O` (valor `None`) nao sai
# do modelo (`outros` so aparece como fallback de rotulo desconhecido no Rust).
TIPOS_QUE_O_CRF_EMITE = frozenset(
    tipo for tipo in TIPOS_SEGMENTO if mapa_tipo_segmento.get(tipo, tipo) is not None
)

# Quantos enderecos vao por chamada ao segmentador (uma linha de entrada e uma
# de saida JSON por endereco).
TAMANHO_BLOCO = 5_000


def validar_tipos(valores: Sequence[str] | None, modelo: Path | None) -> frozenset[str]:
    """Normaliza e valida a lista de `--apenas-tipos`; vazia = filtro desligado.

    Erra com mensagem explicita quando o tipo nao existe na ontologia ou quando
    existe mas o CRF nunca o emite (o treinamento colapsa esses rotulos em `O`).
    """
    if modelo is not None and not modelo.is_file():
        raise typer.BadParameter(f"Modelo CRF não encontrado: {modelo}")
    tipos = frozenset(item.strip().lower() for item in valores or () if item.strip())
    if not tipos:
        return frozenset()

    desconhecidos = sorted(tipos - set(TIPOS_SEGMENTO))
    if desconhecidos:
        raise typer.BadParameter(
            f"Tipo(s) desconhecido(s): {', '.join(desconhecidos)}. "
            f"Válidos: {', '.join(sorted(TIPOS_SEGMENTO))}."
        )
    sem_modelo = sorted(tipos - TIPOS_QUE_O_CRF_EMITE)
    if sem_modelo:
        raise typer.BadParameter(
            f"O CRF não prevê {', '.join(sem_modelo)}: o treinamento colapsa "
            "esses rótulos em `O`. Use um tipo que o modelo emite."
        )
    return tipos


def filtrar_ids_por_tipos(
    saida: Sequence[str], ids: Sequence[int], tipos: frozenset[str]
) -> set[int]:
    """Ids cuja segmentacao (um JSON por linha) tem ao menos um segmento de `tipos`.

    Linha ilegivel conta como nao selecionada: o filtro so inclui quem o modelo
    comprovadamente marcou com um dos tipos pedidos.
    """
    selecionados: set[int] = set()
    for identificador, linha in zip(ids, saida, strict=True):
        try:
            dados = json.loads(linha)
        except json.JSONDecodeError:
            continue
        for segmento in dados.get("segmentos", []):
            if str(segmento.get("tipo", "")) in tipos:
                selecionados.add(identificador)
                break
    return selecionados


def confianca_minima(
    tags: Sequence[str], marginais: Sequence[Mapping[str, float]]
) -> float:
    """Menor probabilidade marginal entre as tags previstas, uma por token."""
    if not tags:
        return 1.0
    return min(
        marginal.get(tag, 1.0)
        for tag, marginal in zip(tags, marginais, strict=True)
    )


def confianca_do_endereco(
    crf: sklearn_crfsuite.CRF, extrator: ExtratorFeature, endereco: str
) -> float:
    """Menor probabilidade marginal entre as tags previstas para os tokens.

    1.0 quando o endereco nao tem token: sem token nao ha tag em que o modelo
    possa estar em duvida.
    """
    x = extrator.tokens2features(tokenize(endereco))
    if not x:
        return 1.0
    return confianca_minima(
        cast(list[str], crf.predict_single(x)),
        cast(list[dict[str, float]], crf.predict_marginals_single(x)),
    )


def filtrar_ids_por_incerteza(
    confiancas: Sequence[float], ids: Sequence[int], limiar: float
) -> set[int]:
    """Ids cuja menor confianca por token fica abaixo de `limiar`."""
    selecionados: set[int] = set()
    for identificador, confianca in zip(ids, confiancas, strict=True):
        if confianca < limiar:
            selecionados.add(identificador)
    return selecionados


def prever_incertos(
    linhas: Sequence[Pendente],
    limiar: float,
    *,
    tagger: Path = CAMINHO_TAGGER,
) -> frozenset[int]:
    """Roda o CRF nos pendentes e devolve os que tem algum token inseguro.

    As probabilidades marginais so existem no modelo Python - o binario Rust
    devolve apenas a segmentacao -, entao aqui o modelo e o `--tagger`.
    """
    crf = carregar_tagger(tagger)
    extrator = ExtratorFeature()
    confiancas: list[float] = []
    with progresso() as barra:
        tarefa = barra.add_task("Medindo a confiança do CRF", total=len(linhas))
        for linha in linhas:
            confiancas.append(confianca_do_endereco(crf, extrator, linha.endereco))
            barra.advance(tarefa)
    return frozenset(
        filtrar_ids_por_incerteza(
            confiancas, [linha.id for linha in linhas], limiar
        )
    )


def prever_tipos(
    linhas: Sequence[Pendente],
    tipos: frozenset[str],
    *,
    modelo: Path | None = None,
    binario: Path | None = None,
) -> frozenset[int]:
    """Roda o CRF nos pendentes e devolve os ids com ao menos um dos `tipos`.

    Usa o binario do proprio enderecobr_rs, entao a predicao e identica a do
    segmentador publicado; o modelo e escolhido por `--modelo-crf`
    (`ENDERECOBR_MODELO` para o binario) ou pelo padrao dele.
    """
    selecionados: set[int] = set()
    with progresso() as barra:
        tarefa = barra.add_task("Prevendo com o CRF", total=len(linhas))
        for inicio in range(0, len(linhas), TAMANHO_BLOCO):
            bloco = linhas[inicio : inicio + TAMANHO_BLOCO]
            saida = rodar_segmentacao(
                [linha.endereco for linha in bloco], modelo=modelo, binario=binario
            )
            selecionados |= filtrar_ids_por_tipos(
                saida, [linha.id for linha in bloco], tipos
            )
            barra.advance(tarefa, len(bloco))
    return frozenset(selecionados)
