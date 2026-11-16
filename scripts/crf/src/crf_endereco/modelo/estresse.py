"""Estresse do tagger: perturbacoes fixas sobre o recorte de teste.

As familias, a fracao de typo e as sementes ficam literais aqui, e cada
perturbacao sorteia a partir do proprio texto: o mesmo comando mede sempre os
mesmos casos e o que muda entre execucoes e so o modelo. Todas as familias
trocam caracteres dentro dos tokens, entao a etiqueta esperada de cada token
continua valendo; a linha em que a contagem de tokens muda sai da conta.
"""

from __future__ import annotations

import random
from collections.abc import Callable

import sklearn_crfsuite
from rich.table import Table
from rich.text import Text
from sklearn_crfsuite import metrics

from crf_endereco.features import ExtratorFeature, normalize, tokenize
from crf_endereco.modelo.crf import Exemplos
from crf_endereco.modelo.relatorio import estilo_fracao, pct, show
from crf_endereco.ui import console

# Tipo de via -> abreviacao que aparece nos cadastros.
ABREVIACOES_TIPO: dict[str, str] = {
    "RUA": "R",
    "AVENIDA": "AV",
    "TRAVESSA": "TV",
    "PRACA": "PC",
    "ALAMEDA": "AL",
    "RODOVIA": "ROD",
    "ESTRADA": "EST",
    "LARGO": "LGO",
    "VILA": "VL",
    "JARDIM": "JD",
    "CONJUNTO": "CJ",
    "LOTEAMENTO": "LOT",
    "PARQUE": "PQ",
    "QUADRA": "QD",
    "SETOR": "ST",
    "BECO": "BC",
}

TAMANHO_TRUNCAMENTO = 3
FRACAO_TYPO_GERAL = 0.15
SEMENTE = 11
AMOSTRAS_ERRO = 1

Perturbacao = Callable[[str], str]


def _acerto(valor: float) -> Text:
    """Fracao em porcentagem, na cor do quao bom ela e."""
    return Text(pct(valor), style=estilo_fracao(valor))


def _indice_cabeca(toks: list[str]) -> int | None:
    """Primeiro token alfanumerico: onde o tipo de via do endereco aparece."""
    for i, tok in enumerate(toks):
        if tok.isalnum():
            return i
    return None


def abreviar_tipo(texto: str) -> str:
    """Troca o tipo de via pela sigla do cadastro (`RUA` -> `R`)."""
    toks = tokenize(texto)
    i = _indice_cabeca(toks)
    if i is None:
        return texto
    sigla = ABREVIACOES_TIPO.get(normalize(toks[i]).upper())
    if sigla is None:
        return texto
    toks[i] = sigla
    return " ".join(toks)


def truncar_tipo(texto: str, tamanho: int = TAMANHO_TRUNCAMENTO) -> str:
    """Corta o tipo de via nas primeiras letras (`AVENIDA` -> `AVE`)."""
    toks = tokenize(texto)
    i = _indice_cabeca(toks)
    if i is None or not toks[i].isalpha() or len(toks[i]) <= tamanho:
        return texto
    toks[i] = toks[i][:tamanho]
    return " ".join(toks)


def truncar_tokens(texto: str, tamanho: int = TAMANHO_TRUNCAMENTO) -> str:
    """Corta todas as palavras nas primeiras letras."""
    return " ".join(
        tok[:tamanho] if tok.isalpha() and len(tok) > tamanho else tok
        for tok in tokenize(texto)
    )


def _editar(palavra: str, sorteio: random.Random) -> str:
    """Uma edicao na palavra: apaga, troca vizinhos ou troca uma letra."""
    if len(palavra) < 4:
        return palavra
    i = sorteio.randrange(len(palavra))
    escolha = sorteio.randrange(3)
    if escolha == 0:
        return palavra[:i] + palavra[i + 1 :]
    if escolha == 1:
        j = min(i + 1, len(palavra) - 1)
        return palavra[:i] + palavra[j] + palavra[i] + palavra[j + 1 :]
    return palavra[:i] + "X" + palavra[i + 1 :]


def typo_no_tipo(texto: str) -> str:
    """Uma edicao no tipo de via (`RUA` -> `RAA`)."""
    toks = tokenize(texto)
    i = _indice_cabeca(toks)
    if i is None or not toks[i].isalpha():
        return texto
    toks[i] = _editar(toks[i], random.Random(f"{SEMENTE}:tipo:{texto}"))
    return " ".join(toks)


def typos_no_endereco(texto: str, fracao: float = FRACAO_TYPO_GERAL) -> str:
    """Uma edicao em cada palavra sorteada do endereco."""
    sorteio = random.Random(f"{SEMENTE}:geral:{texto}")
    return " ".join(
        _editar(tok, sorteio) if tok.isalpha() and sorteio.random() < fracao else tok
        for tok in tokenize(texto)
    )


FAMILIAS: tuple[tuple[str, Perturbacao], ...] = (
    ("abreviacao do tipo", abreviar_tipo),
    ("tipo em 3 letras", truncar_tipo),
    ("tudo em 3 letras", truncar_tokens),
    ("um typo no tipo", typo_no_tipo),
    (f"{round(100 * FRACAO_TYPO_GERAL)}% dos tokens com typo", typos_no_endereco),
)


def rodar(crf: sklearn_crfsuite.CRF, teste: Exemplos) -> None:
    """Mede cada familia de perturbacao sobre o recorte de teste."""
    extrator = ExtratorFeature()
    textos = [" ".join(tokens) for tokens in teste.tokens]

    console.rule("[bold]Estresse[/bold]")
    tabela = Table(box=None, pad_edge=False, padding=(0, 1, 0, 0))
    tabela.add_column("familia")
    tabela.add_column("alterados", justify="right", style="dim")
    tabela.add_column("token", justify="right")
    tabela.add_column("endereco perfeito", justify="right")
    tabela.add_column("B_LOGRADOURO", justify="right")

    amostras: list[tuple[str, list[str], list[str], list[str]]] = []
    mostrados: set[int] = set()
    for nome, perturbar in FAMILIAS:
        perturbados = [perturbar(texto) for texto in textos]
        validos = [
            i
            for i, perturbado in enumerate(perturbados)
            if len(tokenize(perturbado)) == len(teste.y[i])
        ]
        x = [extrator.sent2features(perturbados[i]) for i in validos]
        y = [teste.y[i] for i in validos]
        previsto = [[str(tag) for tag in linha] for linha in crf.predict(x)]

        cabecas = [
            (esperado, predito)
            for linha_esperada, linha_prevista in zip(y, previsto, strict=True)
            for esperado, predito in zip(linha_esperada, linha_prevista, strict=True)
            if esperado == "B_LOGRADOURO"
        ]
        acertos = sum(1 for esperado, predito in cabecas if esperado == predito)
        alterados = sum(1 for i in validos if perturbados[i] != textos[i])
        tokens = metrics.flat_accuracy_score(y, previsto)
        perfeitos = metrics.sequence_accuracy_score(y, previsto)

        tabela.add_row(
            nome,
            str(alterados),
            _acerto(tokens),
            _acerto(perfeitos),
            _acerto(acertos / len(cabecas)) if cabecas else Text("-", style="dim"),
        )

        # Uma amostra por familia, e de um endereco que ainda nao apareceu: as
        # familias que mexem so no tipo erram o mesmo endereco, e repeti-lo em
        # cinco blocos nao mostra nada novo.
        for i, esperado, predito in zip(validos, y, previsto, strict=True):
            if esperado == predito or i in mostrados:
                continue
            if len(amostras) < AMOSTRAS_ERRO * len(FAMILIAS):
                mostrados.add(i)
                amostras.append((nome, perturbados[i].split(), esperado, predito))
            break

    console.print(tabela)
    console.print(
        "[dim]alterados = enderecos que a familia de fato mexeu; token e endereco "
        + "perfeito usam as mesmas etiquetas do dado limpo, entao qualquer queda vem "
        + "da perturbacao. B_LOGRADOURO = acerto do token que abre o logradouro.[/dim]"
    )

    for nome, tokens_perturbados, esperado, predito in amostras:
        console.print()
        console.print(Text(f"Primeiro erro de {nome}", style="bold"))
        show(tokens_perturbados, esperado, predito)
