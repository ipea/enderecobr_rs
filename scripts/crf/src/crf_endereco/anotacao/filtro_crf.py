"""Filtro dos pendentes pelas categorias que o CRF preve."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

import typer

from crf_endereco.anotacao.ontologia import TIPOS_SEGMENTO
from crf_endereco.anotacao.pendentes import Pendente
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
