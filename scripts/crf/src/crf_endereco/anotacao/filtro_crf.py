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
from crf_endereco.modelo.crf import Exemplos, carregar_tagger
from crf_endereco.rotulos import mapa_tipo_segmento
from crf_endereco.ui import progresso

# Rotulos que o CRF consegue emitir: espelham `TipoSegmento::TODOS` do Rust.
# Derivados do proprio mapa: o que o treino colapsa em `O` (valor `None`) nao sai
# do modelo (`outros` so aparece como fallback de rotulo desconhecido no Rust).
TIPOS_QUE_O_CRF_EMITE = frozenset(
    tipo for tipo in TIPOS_SEGMENTO if mapa_tipo_segmento.get(tipo, tipo) is not None
)


# Faixa de confianca `[minimo, maximo)`: abaixo do minimo o caso e perdido, acima
# do maximo e caso facil — nenhum dos dois ensina nada ao modelo.
Faixa = tuple[float, float]


@dataclass(frozen=True)
class Previsao:
    """O que o CRF diz de um pendente: base de todos os filtros de previsao.

    `tags` (uma por token) e o que o `explorar` compara com o rotulo atual;
    `pior_token` e o token onde o modelo ficou menos seguro — o "porque" do
    caso aparecer.
    """

    id: int
    tags: tuple[str, ...]
    tipos: frozenset[str]
    # Menor e media das probabilidades marginais das tags previstas.
    menor_confianca: float
    media_confianca: float
    # Token mais duvidoso e a tag que o modelo previu para ele.
    pior_token: str
    pior_tag: str


def parse_faixa(valor: str | None, opcao: str) -> Faixa | None:
    """Le `--incertos`/`--incertos-media`: `0.8` vira `(0.0, 0.8)`; `0.6,0.8` fica.

    Um valor so continua significando "abaixo de", como antes da faixa existir.
    """
    if valor is None:
        return None
    partes = [parte.strip() for parte in valor.split(",")]
    if len(partes) > 2 or not all(partes):
        raise typer.BadParameter(
            f"{opcao}: use um valor (`0.8`) ou uma faixa (`0.6,0.8`), veio {valor!r}."
        )
    try:
        numeros = [float(parte) for parte in partes]
    except ValueError:
        raise typer.BadParameter(f"{opcao}: valor não numérico em {valor!r}.") from None
    minimo, maximo = (0.0, numeros[0]) if len(numeros) == 1 else numeros
    if not 0.0 <= minimo < maximo <= 1.0:
        raise typer.BadParameter(
            f"{opcao}: espera 0 <= mínimo < máximo <= 1, veio {valor!r}."
        )
    return (minimo, maximo)


def descrever_faixa(faixa: Faixa) -> str:
    """Faixa no formato das mensagens de filtro (`[0.60, 0.80)`)."""
    minimo, maximo = faixa
    return f"[{minimo:.2f}, {maximo:.2f})"


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
    return math.exp(
        math.fsum(math.log(p) for p in probabilidades) / len(probabilidades)
    )


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
            tokens, tags, marginais = _prever_endereco(crf, extrator, linha.endereco)
            pior = _pior_token(tags, marginais)
            previsoes.append(
                Previsao(
                    id=linha.id,
                    tags=tuple(tags),
                    tipos=tipos_das_tags(tags),
                    menor_confianca=confianca_minima(tags, marginais),
                    media_confianca=confianca_media(tags, marginais),
                    pior_token=tokens[pior] if pior is not None else "",
                    pior_tag=tags[pior] if pior is not None else "O",
                )
            )
            barra.advance(tarefa)
    return previsoes


def _pior_token(
    tags: Sequence[str], marginais: Sequence[Mapping[str, float]]
) -> int | None:
    """Indice do token cuja tag prevista tem a menor probabilidade marginal."""
    if not tags:
        return None
    return min(
        range(len(tags)),
        key=lambda i: marginais[i].get(tags[i], 1.0),
    )


def _prever_endereco(
    crf: sklearn_crfsuite.CRF, extrator: ExtratorFeature, endereco: str
) -> tuple[list[str], list[str], list[dict[str, float]]]:
    """Tokens, tags previstas e probabilidades marginais (vazios sem token)."""
    tokens = tokenize(endereco)
    x = extrator.tokens2features(tokens)
    if not x:
        return tokens, [], []
    return (
        tokens,
        cast(list[str], crf.predict_single(x)),
        cast(list[dict[str, float]], crf.predict_marginals_single(x)),
    )


def filtrar_por_tipos(
    previsoes: Sequence[Previsao], tipos: frozenset[str]
) -> frozenset[int]:
    """Ids cuja previsao tem ao menos um dos `tipos`."""
    return frozenset(previsao.id for previsao in previsoes if previsao.tipos & tipos)


def filtrar_por_confianca(
    previsoes: Sequence[Previsao], faixa: Faixa, *, media: bool = False
) -> frozenset[int]:
    """Ids cuja confianca (do token menos confiavel, ou a media) cai na faixa.

    O maximo e aberto: no limiar exato o endereco nao entra, porque o filtro
    quer os casos em duvida.
    """
    minimo, maximo = faixa
    return frozenset(
        previsao.id
        for previsao in previsoes
        if minimo
        <= (previsao.media_confianca if media else previsao.menor_confianca)
        < maximo
    )


@dataclass(frozen=True)
class Divergencia:
    """Um endereco em que o modelo erra o proprio rotulo.

    Guarda as duas etiquetas token a token (a do treino e a prevista): sao elas
    que, comparadas com a resposta da LLM, dizem se a reetiquetacao resolveu o
    caso ou se o modelo e que estava errado.
    """

    hash: str
    rotulos: tuple[str, ...]
    previsto: tuple[str, ...]

    @property
    def pares(self) -> tuple[tuple[str, str], ...]:
        """`(esperado, previsto)` de cada token que o modelo troca."""
        return tuple(
            (real, obtido)
            for real, obtido in zip(self.rotulos, self.previsto, strict=True)
            if real != obtido
        )


def divergencias(crf: sklearn_crfsuite.CRF, exemplos: Exemplos) -> list[Divergencia]:
    """Enderecos em que a previsao do modelo difere do rotulo que o treinou.

    Faz sentido no recorte de treino: ali o modelo ja viu o exemplo, entao o
    erro aponta para rotulo suspeito (ou para um caso ambiguo demais), nunca
    para falta de generalizacao. Sao esses os candidatos a reetiquetacao.
    """
    achados: list[Divergencia] = []
    for hash_, esperado, previsto in zip(
        exemplos.hashes, exemplos.y, crf.predict(exemplos.x), strict=True
    ):
        if esperado == previsto:
            continue
        achados.append(
            Divergencia(hash=hash_, rotulos=tuple(esperado), previsto=tuple(previsto))
        )
    return achados
