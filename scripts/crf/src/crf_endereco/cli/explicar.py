"""Comando didático: dissec a segmentação de um endereço, etapa por etapa."""

from __future__ import annotations

import zlib
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Annotated

import enderecobr
import sklearn_crfsuite
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

# Campos do `Endereco`, na ordem em que `formatar` junta.
CAMPOS = ("logradouro", "numero", "complemento", "localidade", "cep")

# Função de padronização de cada campo (`padronizar_in_place` no Rust).
PADRONIZADORES = {
    "logradouro": enderecobr.padronizar_logradouros,
    "numero": enderecobr.padronizar_numeros,
    "complemento": enderecobr.padronizar_complementos,
    "localidade": enderecobr.padronizar_bairros,
    "cep": enderecobr.padronizar_cep_leniente,
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
    tagger: OpcaoTagger = CAMINHO_TAGGER,
) -> None:
    """Disseca a segmentação de um endereço, etapa por etapa.

    Mostra, na ordem do pipeline real de inferência: tokenização, features do
    CRF com os pesos que sustentam a tag prevista de cada token (mais a tag
    concorrente e a probabilidade marginal), a remontagem dos segmentos
    verbatim e a estruturação deles nos campos do endereço.
    """
    import readline

    crf = modelo_crf.carregar_tagger(tagger)
    extrator = ExtratorFeature()

    while True:
        try:
            endereco = input()
            if not endereco:
                continue

            _entrada(endereco)
            _tokenizacao(endereco)
            _previsao(endereco, extrator, crf)
            _remontagem(endereco, crf)
            _estruturacao(endereco, crf)
        except EOFError:
            break


def _entrada(endereco: str) -> None:
    console.rule("[bold]1. Endereço bruto[/bold]")
    console.print(f'"{endereco}"')
    console.print(
        "[dim]O segmentador só vê essa string: nada de UF, município ou contexto "
        "externo — toda a estrutura sai dos próprios tokens.[/dim]"
    )


def _tokenizacao(endereco: str) -> None:
    tokens_com_offset = tokenize_com_offsets(endereco)
    console.rule("[bold]2. Tokenização[/bold]")
    painel = Text(" │ ").join(Text(tok, style="bold") for tok, _ in tokens_com_offset)
    console.print(painel)
    console.print(
        "[dim]Cada token é uma corrida de letras, uma corrida de números ou um "
        'caractere de pontuação isolado — por isso "S/N" vira três tokens, e a '
        "remontagem é que cola de volta.[/dim]"
    )


def _previsao(
    endereco: str, extrator: ExtratorFeature, crf: sklearn_crfsuite.CRF
) -> None:
    tokens_com_offset = tokenize_com_offsets(endereco)
    tokens = [tok for tok, _ in tokens_com_offset]
    x = extrator.tokens2features(tokens)
    tags = crf.predict_single(x)
    marginais = crf.predict_marginals_single(x)
    state_features = crf.state_features_ or {}

    console.rule("[bold]3. Features, pesos e previsão, token a token[/bold]")
    tabela = Table(box=None, padding=(0, 2, 0, 0))
    tabela.add_column("#", justify="right", style="dim")
    tabela.add_column("token", style="bold")
    tabela.add_column(
        "features e pesos (p/ a tag prevista)", overflow="fold", max_width=64
    )
    tabela.add_column("tag prevista (p)")
    tabela.add_column("2ª (p)", justify="right")

    for i, (tok, tag) in enumerate(zip(tokens, tags, strict=True)):
        prob = marginais[i].get(tag, float("nan"))
        rival, p_rival = _concorrente(marginais[i], tag)
        prevista = _texto_tag(tag)
        prevista.append(f" {prob:.3f}", style="dim")
        tabela.add_row(
            str(i),
            tok,
            features_com_pesos(x[i], tag, state_features),
            prevista,
            Text(f"{rival} {p_rival:.3f}", style="dim"),
        )
    console.print(tabela)
    console.print(
        "[dim]O CRF nem olha para as palavras: cada token vira essas features. O "
        "peso segue um mapa de calor — verde soma a favor da tag prevista, "
        "vermelho empurra contra, cor forte = peso grande; o traço marca "
        "combinação sem peso no treino. O número ao lado da tag é a "
        "probabilidade marginal dela, e a coluna 2ª é a rival mais próxima — "
        "quanto mais empatadas, mais vale ler os pesos com atenção.[/dim]"
    )
    _glossario()


def _glossario() -> None:
    tabela = Table(box=None, show_header=False, padding=(0, 1, 0, 0))
    tabela.add_column(style="dim")
    tabela.add_column(style="dim")
    for exemplo, significado in [
        ("bias, 2_pos", "sempre presente; _pos = faixa de posição do token (0–3)"),
        ("0:RUA", "a própria palavra, normalizada e em maiúsculas"),
        ("0:tam:6", "comprimento da palavra (máx. 10; zeros à esquerda ignorados)"),
        ("-1:APTO, 2:CENTRO", "palavra do vizinho; a busca salta pontuação"),
        ("0:is_digit/alpha/punct", "só um desses tipos por token"),
        ("0:marcador_df / palmas", "vocabulário típico de Brasília / Palmas"),
        ("0:sigla_estado", "UF (SP, RJ, …)"),
        ("tem_pontuacao:2", "havia pontuação a caminho do vizinho 2"),
        ("BOS, EOS", "primeiro / último token do endereço"),
    ]:
        tabela.add_row(exemplo, significado)
    console.print()
    console.print(tabela)


def _remontagem(endereco: str, crf: sklearn_crfsuite.CRF) -> None:
    tokens_com_offset, _, tags, _, segmentos = _prever(endereco, ExtratorFeature(), crf)
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


def _estruturacao(endereco: str, crf: sklearn_crfsuite.CRF) -> None:
    _, _, _, _, segmentos = _prever(endereco, ExtratorFeature(), crf)
    console.rule("[bold]5. Estruturação do endereço[/bold]")
    if not segmentos:
        console.print("[yellow]nenhum segmento para estruturar[/yellow]")
        return

    campos = estruturar_segmentos(segmentos)

    padronizados = _padronizar(campos)
    resultado = Table(box=None, padding=(0, 2, 0, 0))
    resultado.add_column("campo", justify="right")
    resultado.add_column("bruto", overflow="fold")
    resultado.add_column("padronizado", overflow="fold")
    for campo, valor in campos.items():
        if valor is None:
            continue
        resultado.add_row(
            Text(campo, style=_estilo_tipo(campo)),
            valor,
            padronizados[campo] or "",
        )
    console.print(resultado)
    console.print()
    console.print(Text(_formatar(padronizados), style="bold"))
    console.print(
        "[dim]O valor entra no campo verbatim e é a padronização de cada campo que "
        "muda o texto (logradouro pelo léxico de tipos de via, número por extenso, "
        "complemento e bairro por substituição, cep com hífen); o pipeline real "
        "chama `estruturar_segmentos` com `padronizar=True`, então é essa linha "
        "que segue para o geocodebr.[/dim]"
    )


def estruturar_segmentos(
    segmentos: Sequence[Mapping[str, str]],
) -> dict[str, str | None]:
    """Espelha `estruturar_segmentos` do Rust (`estruturacao.rs`).

    Cada trecho fica no primeiro campo livre da sua lista de preferência; trecho
    sem lista, ou com todos os campos dela já ocupados, é descartado. Parcela e
    complemento são concatenáveis: entram em sequência no campo já preenchido.
    """
    campos: dict[str, str | None] = dict.fromkeys(CAMPOS)
    for i, segmento in enumerate(segmentos):
        preferidos, concatenar = campos_preferidos(
            segmento.get("tipo", ""),
            segmentos[i - 1].get("tipo") if i else None,
        )
        for campo in preferidos:
            valor = segmento.get("valor", "")
            if campos[campo] is None:
                campos[campo] = valor
                break
            if concatenar:
                campos[campo] = f"{campos[campo]} {valor}"
                break
    return campos


def campos_preferidos(tipo: str, anterior: str | None) -> tuple[list[str], bool]:
    """Campos que o trecho pode ocupar, na ordem de preferência, e se concatenam.

    A lista vazia descarta o trecho. A ordem dos casos é a mesma do Rust: o
    primeiro que casa manda.
    """
    if tipo == "logradouro":
        return ["logradouro"], False
    if tipo in ("numero", "quilometragem_via"):
        return ["numero", "complemento"], False
    if tipo == "cep":
        return ["cep"], False
    if tipo == "parcela":
        if anterior == "logradouro":
            return ["logradouro"], True
        return ["logradouro", "complemento"], True
    if tipo in ("nucleo_rural", "recurso_natural", "empreendimento", "ponto_referencia"):
        return ["logradouro", "localidade"], False
    if tipo == "complemento":
        return ["complemento"], True
    if tipo == "localidade":
        return ["localidade"], False
    return [], False


def _padronizar(campos: Mapping[str, str | None]) -> dict[str, str | None]:
    return {
        campo: None if valor is None else PADRONIZADORES[campo](valor)
        for campo, valor in campos.items()
    }


def _formatar(campos: Mapping[str, str | None]) -> str:
    return ", ".join(valor.strip() for valor in campos.values() if valor is not None)


def _prever(
    endereco: str, extrator: ExtratorFeature, crf: sklearn_crfsuite.CRF
) -> tuple[
    list[tuple[str, int]],
    list[dict[str, float]],
    list[str],
    list[dict[str, float]],
    list[dict[str, str]],
]:
    tokens_com_offset = tokenize_com_offsets(endereco)
    tokens = [tok for tok, _ in tokens_com_offset]
    x = extrator.tokens2features(tokens)
    tags = crf.predict_single(x)
    marginais = crf.predict_marginals_single(x)
    segmentos = modelo_crf.montar_segmentos(endereco, tokens_com_offset, tags)
    return tokens_com_offset, x, tags, marginais, segmentos


def _concorrente(marginal: Mapping[str, float], tag: str) -> tuple[str, float]:
    return max(
        (par for par in marginal.items() if par[0] != tag),
        key=lambda par: par[1],
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
