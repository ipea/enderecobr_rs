"""Filtros dos pendentes pelas previsoes e confiancas do CRF."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
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
from crf_endereco.ui import progresso

# Rotulos que o CRF consegue emitir: espelham `TipoSegmento::TODOS` do Rust.
# Derivados do proprio mapa: o que o treino colapsa em `O` (valor `None`) nao sai
# do modelo (`outros` so aparece como fallback de rotulo desconhecido no Rust).
TIPOS_QUE_O_CRF_EMITE = frozenset(
    tipo for tipo in TIPOS_SEGMENTO if mapa_tipo_segmento.get(tipo, tipo) is not None
)


@dataclass(frozen=True)
class Previsao:
    """O que o CRF diz de um pendente: base de todos os filtros de previsao."""

    id: int
    tipos: frozenset[str]
    # Menor e media das probabilidades marginais das tags previstas.
    menor_confianca: float
    media_confianca: float


def validar_tipos(valores: Sequence[str] | None) -> frozenset[str]:
    """Normaliza e valida a lista de `--apenas-tipos`; vazia = filtro desligado.

    Erra com mensagem explicita quando o tipo nao existe na ontologia ou quando
    existe mas o CRF nunca o emite (o treinamento colapsa esses rotulos em `O`).
    """
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


def tipos_das_tags(tags: Sequence[str]) -> frozenset[str]:
    """Tipos que as tags BIO preveem (`B_LOGRADOURO` -> `logradouro`)."""
    return frozenset(tag.partition("_")[2].lower() for tag in tags if tag != "O")


def confianca_minima(
    tags: Sequence[str], marginais: Sequence[Mapping[str, float]]
) -> float:
    """Menor probabilidade marginal entre as tags previstas, uma por token."""
    if not tags:
        return 1.0
    return min(
        marginal.get(tag, 1.0) for tag, marginal in zip(tags, marginais, strict=True)
    )


def confianca_media(
    tags: Sequence[str], marginais: Sequence[Mapping[str, float]]
) -> float:
    """Media geometrica das probabilidades marginais entre as tags previstas.

    Normalizada pelo tamanho, como a `confianca` do Rust: nao cai com o numero
    de tokens, mas um unico token em duvida puxa o valor inteiro para baixo.

    1.0 quando o endereco nao tem token: sem token nao ha tag em que o modelo
    possa estar em duvida.
    """
    if not tags:
        return 1.0
    probabilidades = [
        marginal.get(tag, 1.0) for tag, marginal in zip(tags, marginais, strict=True)
    ]
    if any(probabilidade <= 0.0 for probabilidade in probabilidades):
        return 0.0
    return math.exp(math.fsum(math.log(p) for p in probabilidades) / len(probabilidades))


def prever(linhas: Sequence[Pendente], modelo: Path = CAMINHO_TAGGER) -> list[Previsao]:
    """Roda o CRF uma vez por pendente e resume o que o modelo previu.

    Uma passada unica serve a todos os filtros: ligar `--apenas-tipos`,
    `--incertos` e `--incertos-media` juntos nao custa tres predicoes.
    """
    crf = carregar_tagger(modelo)
    extrator = ExtratorFeature()
    previsoes: list[Previsao] = []
    with progresso() as barra:
        tarefa = barra.add_task("Prevendo com o CRF", total=len(linhas))
        for linha in linhas:
            tags, marginais = _prever_endereco(crf, extrator, linha.endereco)
            previsoes.append(
                Previsao(
                    id=linha.id,
                    tipos=tipos_das_tags(tags),
                    menor_confianca=confianca_minima(tags, marginais),
                    media_confianca=confianca_media(tags, marginais),
                )
            )
            barra.advance(tarefa)
    return previsoes


def _prever_endereco(
    crf: sklearn_crfsuite.CRF, extrator: ExtratorFeature, endereco: str
) -> tuple[list[str], list[dict[str, float]]]:
    """Tags previstas e probabilidades marginais, vazias quando nao ha token."""
    x = extrator.tokens2features(tokenize(endereco))
    if not x:
        return [], []
    return (
        cast(list[str], crf.predict_single(x)),
        cast(list[dict[str, float]], crf.predict_marginals_single(x)),
    )


def filtrar_por_tipos(
    previsoes: Sequence[Previsao], tipos: frozenset[str]
) -> frozenset[int]:
    """Ids cuja previsao tem ao menos um dos `tipos`."""
    return frozenset(previsao.id for previsao in previsoes if previsao.tipos & tipos)


def filtrar_por_confianca(
    previsoes: Sequence[Previsao], limiar: float, *, media: bool = False
) -> frozenset[int]:
    """Ids cuja confianca (do token menos confiavel, ou a media) fica abaixo.

    No limiar exato o endereco nao entra: o filtro quer os casos em duvida.
    """
    return frozenset(
        previsao.id
        for previsao in previsoes
        if (previsao.media_confianca if media else previsao.menor_confianca) < limiar
    )
