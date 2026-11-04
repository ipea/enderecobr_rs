"""Comando didático: dissec a segmentação de um endereço, etapa por etapa."""

from __future__ import annotations

import zlib
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Annotated

import typer
from rich.table import Table
from rich.text import Text

from crf_endereco.config import CAMINHO_TAGGER
from crf_endereco.features import ExtratorFeature, tokenize_com_offsets
from crf_endereco.modelo import crf as modelo_crf
from crf_endereco.ui import console

OpcaoTagger = Annotated[Path, typer.Option(help="tagger treinado")]

CORES_TIPO = {
    "logradouro": "cyan",
    "numero": "bright_magenta",
    "complemento": "yellow",
    "parcela": "green",
    "empreendimento": "bright_blue",
    "localidade": "blue",
    "nucleo_rural": "bright_cyan",
    "recurso_natural": "bright_green",
    "referencia": "magenta",
    "ponto_referencia": "bright_yellow",
    "denominacao": "bright_red",
    "quilometragem_via": "color(202)",
    "cep": "red",
    "municipio": "color(99)",
    "uf": "color(135)",
}

# Tipos novos, se surgirem, caem em uma cor estável derivada do nome.
FALLBACK_CORES = [
    "color(75)",
    "color(214)",
    "color(213)",
    "color(80)",
    "color(171)",
    "color(117)",
    "color(137)",
    "color(179)",
]


def explicar(
    endereco: Annotated[str, typer.Argument(help="endereço a dissecar")],
    tagger: OpcaoTagger = CAMINHO_TAGGER,
) -> None:
    """Disseca a segmentação de um endereço, etapa por etapa.

    Mostra, na ordem do pipeline real de inferência: tokenização, features do
    CRF com os pesos aprendidos que sustentam a tag prevista de cada token
    (com a probabilidade marginal), e a remontagem dos segmentos verbatim.
    """
    crf = modelo_crf.carregar_tagger(tagger)
    extrator = ExtratorFeature()
    tokens_com_offset = tokenize_com_offsets(endereco)
    tokens = [tok for tok, _ in tokens_com_offset]
    x = extrator.tokens2features(tokens)
    tags = crf.predict_single(x)
    marginais = crf.predict_marginals_single(x)
    segmentos = modelo_crf.montar_segmentos(endereco, tokens_com_offset, tags)

    _entrada(endereco)
    _tokenizacao(tokens)
    _previsao(tokens, x, tags, marginais, crf.state_features_ or {})
    _remontagem(endereco, tokens_com_offset, tags, segmentos)


def _entrada(endereco: str) -> None:
    console.rule("[bold]1. Endereço bruto[/bold]")
    console.print(f'"{endereco}"')
    console.print(
        "[dim]O segmentador só vê essa string: nada de UF, município ou contexto "
        "externo — toda a estrutura sai dos próprios tokens.[/dim]"
    )


def _tokenizacao(tokens: list[str]) -> None:
    console.rule("[bold]2. Tokenização[/bold]")
    painel = Text(" │ ").join(Text(tok, style="bold") for tok in tokens)
    console.print(painel)
    console.print(
        "[dim]Cada token é uma corrida de letras, uma corrida de números ou um "
        'caractere de pontuação isolado — por isso "S/N" vira três tokens, e a '
        "remontagem é que cola de volta.[/dim]"
    )


def _previsao(
    tokens: list[str],
    x: list[dict[str, float]],
    tags: list[str],
    marginais: Sequence[Mapping[str, float]],
    state_features: Mapping[tuple[str, str], float],
) -> None:
    console.rule("[bold]3. Features, pesos e previsão, token a token[/bold]")
    tabela = Table(box=None, padding=(0, 2, 0, 0))
    tabela.add_column("#", justify="right", style="dim")
    tabela.add_column("token", style="bold")
    tabela.add_column(
        "features e pesos (p/ a tag prevista)", overflow="fold", max_width=72
    )
    tabela.add_column("tag prevista")
    tabela.add_column("p", justify="right")

    for i, (tok, tag) in enumerate(zip(tokens, tags, strict=True)):
        prob = marginais[i].get(tag, float("nan"))
        tabela.add_row(
            str(i),
            tok,
            features_com_pesos(x[i], tag, state_features),
            _texto_tag(tag),
            f"{prob:.3f}",
        )
    console.print(tabela)
    console.print(
        "[dim]O CRF nem olha para as palavras: cada token vira essas features "
        "(bias, posição, tamanho, vizinhos ±2...). O peso ao lado segue um mapa "
        "de calor: verde puxa a favor da tag, vermelho empurra contra — quanto "
        "mais forte a cor, maior o peso; um traço marca combinação que ficou "
        "sem peso no treino (min_freq). A soma dessas contribuições, mais as "
        "soma dessas contribuições, mais as transições entre tags, dá a "
        "probabilidade ao lado.[/dim]"
    )


def _remontagem(
    endereco: str,
    tokens_com_offset: list[tuple[str, int]],
    tags: list[str],
    segmentos: list[dict[str, str]],
) -> None:
    console.rule("[bold]4. Remontagem dos segmentos[/bold]")
    if not segmentos:
        console.print("[yellow]nenhum segmento reconhecido[/yellow]")
        return
    for segmento in segmentos:
        tipo = segmento.get("tipo", "")
        estilo = _estilo_tipo(tipo)
        console.print(f"[{estilo}]{tipo:<18}[/{estilo}] {segmento.get('valor', '')}")
    console.print()
    console.print(_texto_colorido(endereco, tokens_com_offset, tags))
    console.print(
        "[dim]Os valores voltam verbatim — o espaço entre tokens só é refeito "
        'se existia no texto bruto, então "S/N" e "310A" sobrevivem.[/dim]'
    )


def features_com_pesos(
    feats: Mapping[str, float],
    tag: str,
    state_features: Mapping[tuple[str, str], float],
) -> Text:
    """Features ordenadas por |peso| para a tag, com `—` quando ficou sem peso."""
    com_peso: list[tuple[float, str]] = []
    sem_peso: list[str] = []
    for attr in feats:
        peso = state_features.get((attr, tag))
        if peso is None:
            sem_peso.append(attr)
        else:
            com_peso.append((peso, attr))
    com_peso.sort(key=lambda p: abs(p[0]), reverse=True)

    texto = Text()
    for peso, attr in com_peso:
        texto.append(f"{attr} ")
        texto.append(f"{peso:+.1f} ", style=_estilo_peso(peso))
    for attr in sem_peso:
        texto.append(f"{attr} ")
        texto.append("— ", style="dim")
    return texto


def _estilo_peso(peso: float) -> str:
    """Mapa de calor divergente: verde a favor, vermelho contra; cor forte = |peso| alto."""
    if peso >= 3:
        return "bold color(46)"
    if peso >= 1.5:
        return "color(40)"
    if peso > 0:
        return "color(114)"
    if peso > -1.5:
        return "color(217)"
    if peso > -3:
        return "color(203)"
    return "bold color(196)"


def _texto_colorido(
    endereco: str,
    tokens_com_offset: list[tuple[str, int]],
    tags: list[str],
) -> Text:
    texto = Text(endereco)
    for (tok, offset), tag in zip(tokens_com_offset, tags, strict=True):
        estilo = "dim" if tag == "O" else _estilo_tipo(tag.split("_", 1)[1].lower())
        texto.stylize(estilo, offset, offset + len(tok))
    return texto


def _texto_tag(tag: str) -> Text:
    if tag == "O":
        return Text("O", style="dim")
    bio, tipo = tag.split("_", 1)
    estilo = _estilo_tipo(tipo.lower())
    if bio == "B":
        estilo = f"bold {estilo}"
    return Text(tag, style=estilo)


def _estilo_tipo(tipo: str) -> str:
    return (
        CORES_TIPO.get(tipo)
        or FALLBACK_CORES[zlib.crc32(tipo.encode()) % len(FALLBACK_CORES)]
    )
