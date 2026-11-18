"""Metricas e relatorio de avaliacao do CRF.

O relatorio sempre le o recorte gravado pelo treino e mostra o teste ao lado do
treino: acuracia alta no treino e baixa no teste e o unico sinal honesto de
generalizacao, e a diferenca entre os dois e a primeira coisa da saida.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from math import ceil
from typing import TYPE_CHECKING

import sklearn_crfsuite
from rich.table import Table
from rich.text import Text

from crf_endereco.ui import console, estilo_rotulo

if TYPE_CHECKING:
    from crf_endereco.modelo.crf import Exemplos

Features = list[list[dict[str, float]]]
Rotulos = list[list[str]]

# Mesma ordem em que `carregar_exemplos` monta `Exemplos.categorias`.
NOMES_CATEGORIAS = ("origem", "uf")

# Abaixo desta queda de acuracia entre treino e teste (em pontos percentuais de
# token) o modelo aprendeu o que estava sendo avaliado: um CRF com alguns
# milhares de exemplos nao generaliza tao bem.
QUEDA_MINIMA_TOKEN = 0.5

# Quanto o relatorio detalha.
TOP_TOKENS = 12


@dataclass(frozen=True)
class Desempenho:
    """Acerto de um recorte inteiro, por token e por endereco."""

    token: float
    perfeitos: int
    enderecos: int
    proporcional: float

    @property
    def fracao_perfeita(self) -> float:
        return self.perfeitos / self.enderecos if self.enderecos else 0.0


def medir(y: Rotulos, previsto: Rotulos) -> Desempenho:
    """Acerto de token, de endereco inteiro e a media por endereco.

    `perfeitos` conta o endereco em que **todos** os rotulos sairam certos: e a
    metrica que o uso real cobra, porque um endereco com um token trocado sai
    errado do segmentador tanto quanto um errado por inteiro.
    """
    if not y:
        return Desempenho(0.0, 0, 0, 0.0)

    acertos = [
        sum(1 for t, p in zip(linha, prev, strict=True) if t == p)
        for linha, prev in zip(y, previsto, strict=True)
    ]
    tokens = sum(len(linha) for linha in y)
    return Desempenho(
        token=sum(acertos) / tokens if tokens else 0.0,
        perfeitos=sum(
            1 for linha, n in zip(y, acertos, strict=True) if n == len(linha)
        ),
        enderecos=len(y),
        proporcional=sum(n / len(linha) for linha, n in zip(y, acertos, strict=True))
        / len(y),
    )


def _prever(crf: sklearn_crfsuite.CRF, x: Features) -> Rotulos:
    return [[str(tag) for tag in linha] for linha in crf.predict(x)]


def pct(valor: float) -> str:
    """Fracao em porcentagem, que e como o relatorio inteiro le acerto."""
    return f"{100 * valor:.2f}%"


def estilo_fracao(valor: float, bom: float = 0.99, medio: float = 0.95) -> str:
    """Cor da fracao: verde no bom, amarelo no meio, vermelho abaixo."""
    if valor >= bom:
        return "green"
    if valor >= medio:
        return "yellow"
    return "bold red"


def _queda(diferenca: float) -> Text:
    """Diferenca de acerto entre treino e teste, em pontos percentuais.

    Queda pequena e o esperado; queda quase nula levanta a suspeita contraria,
    a de que o treino decorou o teste, e por isso sai em vermelho.
    """
    pontos = 100 * diferenca
    estilo = "red" if pontos > QUEDA_MINIMA_TOKEN else "green"
    return Text(f"{pontos:+.2f}pp", style=estilo)


def _cabecalho(treino: Desempenho | None, teste: Desempenho) -> None:
    """Tamanho do recorte e resumo de acerto, com o treino como referencia."""
    plural = "" if teste.enderecos == 1 else "s"
    recorte = f"{teste.enderecos} endereco{plural} no teste"
    if treino is not None:
        recorte = f"{treino.enderecos} no treino | {recorte}"
    console.print(f"[dim]Recorte:[/dim] {recorte}")

    tabela = Table(box=None, pad_edge=False, padding=(0, 2, 0, 0))
    tabela.add_column("", style="dim")
    tabela.add_column("treino", justify="right")
    tabela.add_column("teste", justify="right")
    tabela.add_column("queda", justify="right")

    referencias = [
        ("token", None if treino is None else treino.token, teste.token),
        (
            "endereco perfeito",
            None if treino is None else treino.fracao_perfeita,
            teste.fracao_perfeita,
        ),
        (
            # Media, por endereco, da fracao de tokens certos: um endereco
            # de 30 tokens nao pesa 15x mais que um de 2, e um endereco
            # quase certo ainda soma.
            "token certo por endereco",
            None if treino is None else treino.proporcional,
            teste.proporcional,
        ),
    ]
    for nome, valor_treino, valor_teste in referencias:
        tabela.add_row(
            nome,
            "-" if valor_treino is None else pct(valor_treino),
            pct(valor_teste),
            "-" if valor_treino is None else _queda(valor_treino - valor_teste),
        )

    console.print(tabela)
    perfeitos = f"{teste.perfeitos}/{teste.enderecos} no teste"
    if treino is not None:
        perfeitos += f" e {treino.perfeitos}/{treino.enderecos} no treino"
    console.print(f"[dim]Enderecos com todos os rotulos certos: {perfeitos}.[/dim]")

    if treino is not None and 100 * (treino.token - teste.token) < QUEDA_MINIMA_TOKEN:
        console.print(
            "[bold red]Suspeita de vazamento:[/bold red] o teste acerta tanto quanto "
            + "o treino. Este tagger provavelmente foi treinado com os enderecos "
            + "que estao sendo avaliados."
        )


def contagens_por_rotulo(
    y: Rotulos, previsto: Rotulos
) -> list[tuple[str, int, int, int]]:
    """(rotulo, acertos, falsos positivos, falsos negativos), pior primeiro."""
    acertos: Counter[str] = Counter()
    positivos: Counter[str] = Counter()
    previstos: Counter[str] = Counter()
    for true, pred in zip(y, previsto, strict=True):
        for t, p in zip(true, pred, strict=True):
            positivos[t] += 1
            previstos[p] += 1
            if t == p:
                acertos[t] += 1

    # O rotulo pode existir so na previsao (falso positivo puro): a tabela tem
    # que mostrar o par real x previsto inteiro, nao so o que aparece no dado.
    linhas = [
        (
            rotulo,
            acertos[rotulo],
            previstos[rotulo] - acertos[rotulo],
            positivos[rotulo] - acertos[rotulo],
        )
        for rotulo in set(positivos) | set(previstos)
    ]
    linhas.sort(key=lambda linha: linha[0])
    linhas.sort(key=lambda linha: linha[3] + linha[2], reverse=True)
    return linhas


def _por_rotulo(y: Rotulos, previsto: Rotulos) -> None:
    console.rule("[bold]Por rotulo[/bold]")
    tabela = Table(box=None, pad_edge=False, padding=(0, 2, 0, 0))
    tabela.add_column("rotulo")
    tabela.add_column("tokens", justify="right", style="dim")
    tabela.add_column("precisao", justify="right")
    tabela.add_column("revocacao", justify="right")
    tabela.add_column("f1", justify="right")
    tabela.add_column("erros", justify="right")

    total_acertos = total_positivos = total_previstos = 0
    for rotulo, tp, fp, fn in contagens_por_rotulo(y, previsto):
        precisao = tp / (tp + fp) if tp + fp else 0.0
        revocacao = tp / (tp + fn) if tp + fn else 0.0
        f1 = (
            2 * precisao * revocacao / (precisao + revocacao)
            if precisao + revocacao
            else 0.0
        )
        total_acertos += tp
        total_positivos += tp + fn
        total_previstos += tp + fp
        tabela.add_row(
            Text(rotulo, style=estilo_rotulo(rotulo)),
            str(tp + fn),
            pct(precisao),
            pct(revocacao),
            Text(pct(f1), style=estilo_fracao(f1)),
            str(fp + fn),
        )

    precisao_geral = total_acertos / total_previstos if total_previstos else 0.0
    revocacao_geral = total_acertos / total_positivos if total_positivos else 0.0
    f1_geral = (
        2 * precisao_geral * revocacao_geral / (precisao_geral + revocacao_geral)
        if precisao_geral + revocacao_geral
        else 0.0
    )
    tabela.add_section()
    tabela.add_row(
        Text("micro", style="bold"),
        str(total_positivos),
        pct(precisao_geral),
        pct(revocacao_geral),
        Text(pct(f1_geral), style="bold"),
        str(total_previstos - total_acertos + total_positivos - total_acertos),
    )
    console.print(tabela)
    console.print(
        "[dim]Ordenado por erros (falsos positivos + falsos negativos): o rotulo "
        + "do topo e o que mais custa hoje. Precisao baixa = o modelo etiqueta "
        + "demais aquele trecho; revocacao baixa = deixa passar.[/dim]"
    )


def _por_categoria(teste: Exemplos, previsto: Rotulos) -> None:
    console.rule("[bold]Por categoria[/bold]")
    for pos, nome in enumerate(NOMES_CATEGORIAS):
        if pos >= len(teste.categorias[0]):
            break
        grupos: dict[str, list[int]] = defaultdict(list)
        for i, categoria in enumerate(teste.categorias):
            grupos[categoria[pos]].append(i)

        tabela = Table(box=None, pad_edge=False, padding=(0, 2, 0, 0))
        tabela.add_column(nome)
        tabela.add_column("enderecos", justify="right", style="dim")
        tabela.add_column("endereco perfeito", justify="right")
        tabela.add_column("token", justify="right")

        desempenhos = [
            (
                valor,
                medir([teste.y[i] for i in indices], [previsto[i] for i in indices]),
            )
            for valor, indices in grupos.items()
        ]
        for valor, desempenho in sorted(
            desempenhos, key=lambda par: (par[1].fracao_perfeita, par[1].token)
        ):
            tabela.add_row(
                valor,
                str(desempenho.enderecos),
                Text(
                    pct(desempenho.fracao_perfeita),
                    style=estilo_fracao(desempenho.fracao_perfeita),
                ),
                Text(pct(desempenho.token), style=estilo_fracao(desempenho.token)),
            )
        console.print(tabela)
        console.print()
    console.print(
        "[dim]Ordenado pelo endereco perfeito, pior primeiro: o topo e a "
        + "categoria que mais custa hoje.[/dim]"
    )


def erros_mais_comuns_token(
    x: Features, y_true: Rotulos, y_pred: Rotulos, n: int = TOP_TOKENS
) -> list[tuple[tuple[str, str, str], int]]:
    """Tokens que mais aparecem mal classificados."""
    errors: Counter[tuple[str, str, str]] = Counter()
    for feats, true, pred in zip(x, y_true, y_pred, strict=False):
        for i, (t, p) in enumerate(zip(true, pred, strict=False)):
            if t != p:
                token_atual = [f[2:] for f in feats[i] if f.startswith("0:")]
                if token_atual:
                    errors[(str(token_atual[0]), f"true={t}", f"pred={p}")] += 1
    return errors.most_common(n)


def _tokens_mais_errados(x: Features, y: Rotulos, previsto: Rotulos) -> None:
    console.rule("[bold]Tokens mais errados[/bold]")
    erros = erros_mais_comuns_token(x, y, previsto)
    if not erros:
        console.print("[green]Nenhum token errado.[/green]")
        return

    tabela = Table(box=None, pad_edge=False, padding=(0, 2, 0, 0))
    tabela.add_column("token", style="bold")
    tabela.add_column("esperado")
    tabela.add_column("previsto")
    tabela.add_column("vezes", justify="right", style="dim")
    for (token, esperado, previsto_), contagem in erros:
        tabela.add_row(
            token,
            Text(esperado.removeprefix("true="), style="yellow"),
            Text(
                previsto_.removeprefix("pred="),
                style=estilo_rotulo(previsto_.removeprefix("pred=")),
            ),
            str(contagem),
        )
    console.print(tabela)


def show(sent: Sequence[str], y_true: Sequence[str], y_pred: Sequence[str]) -> None:
    """Imprime um trecho com o rotulo real e o previsto lado a lado.

    O que saiu certo fica apagado; so o token errado aparece com o real em
    amarelo e o previsto na cor do rotulo, para achar a troca de relance.
    """
    if len(sent) == 0:
        return
    tabela = Table(box=None, pad_edge=False, padding=(0, 1, 0, 0), header_style="dim")
    tabela.add_column("token", style="bold")
    tabela.add_column("esperado")
    tabela.add_column("previsto")
    for token, esperado, previsto in zip(sent, y_true, y_pred, strict=False):
        certo = esperado == previsto
        tabela.add_row(
            token,
            Text(esperado, style="dim" if certo else "yellow"),
            Text(previsto, style="dim" if certo else estilo_rotulo(previsto)),
        )
    console.print(tabela)


# Tons de cinza do xterm (233 = escuro, 249 = claro): o fundo segue a
# contagem, e o texto vira preto ou branco conforme a luminância do tom para
# sobreviver tanto a tema claro quanto a escuro.
TONS_CONFUSAO = (233, 237, 240, 244, 248)


def matriz_confusao(
    y_true: Rotulos, y_pred: Rotulos
) -> tuple[list[str], list[list[int]]]:
    """Contagens token a token (real x previsto), em ordem alfabetica."""
    rotulos = sorted(
        {r for linha in y_true for r in linha} | {r for linha in y_pred for r in linha}
    )
    indice = {rotulo: i for i, rotulo in enumerate(rotulos)}
    matriz = [[0] * len(rotulos) for _ in rotulos]
    for true, pred in zip(y_true, y_pred, strict=False):
        for t, p in zip(true, pred, strict=False):
            matriz[indice[t]][indice[p]] += 1
    return rotulos, matriz


def matriz_erros(y_true: Rotulos, y_pred: Rotulos) -> tuple[list[str], list[list[int]]]:
    """Contagens real x previsto sem a diagonal, só dos rótulos que erram.

    Acerto não é erro de ninguém: a diagonal sai da matriz e o rótulo que nunca
    aparece em nenhum erro, nem como real nem como previsto, fica de fora.
    """
    rotulos, matriz = matriz_confusao(y_true, y_pred)
    tamanho = len(matriz)
    erros_linha = [sum(linha) - linha[i] for i, linha in enumerate(matriz)]
    erros_coluna = [
        sum(matriz[i][j] for i in range(tamanho)) - matriz[j][j] for j in range(tamanho)
    ]
    mantidos = [i for i in range(tamanho) if erros_linha[i] or erros_coluna[i]]
    return (
        [rotulos[i] for i in mantidos],
        [[0 if i == j else matriz[i][j] for j in mantidos] for i in mantidos],
    )


def _largura_contagem(matriz: list[list[int]]) -> int:
    """Largura da maior contagem da matriz, já abreviada."""
    return max(len(_contagem(valor)) for linha in matriz for valor in linha)


def _contagem(valor: int) -> str:
    """Contagem em ate cinco caracteres, para a matriz caber na largura util."""
    if valor < 1_000:
        return str(valor)
    if valor < 100_000:
        return f"{valor / 1_000:.1f}k"
    return f"{valor / 1_000:.0f}k"


def _celula(valor: int, maximo: int) -> Text:
    if valor == 0:
        return Text("·", style="color(240)", justify="right")
    nivel = min(len(TONS_CONFUSAO) - 1, len(TONS_CONFUSAO) * valor // maximo)
    tom = TONS_CONFUSAO[nivel]
    frente = "black" if tom >= 244 else "white"
    return Text(_contagem(valor), style=f"{frente} on color({tom})", justify="right")


def imprimir_erros_por_rotulo(y_true: Rotulos, y_pred: Rotulos) -> None:
    """Heatmap dos erros (real x previsto), com as colunas em blocos.

    As colunas são numeradas para não gastar largura com rótulos longos: a
    linha de cada índice está na primeira coluna, então a célula (i, j) se lê
    direto pelos nomes das linhas. O fundo acompanha a fração do maior erro de
    cada linha e o total de erros da linha vem entre parênteses.
    """
    rotulos, matriz = matriz_erros(y_true, y_pred)
    if not rotulos:
        console.print("[green]Nenhum erro de rótulo.[/green]")
        return

    largura_terminal = console.width if console.is_terminal else 200
    largura_rotulo = max(len(rotulo) for rotulo in rotulos) + 9
    # A largura da célula também comporta o índice da coluna.
    largura_celula = max(len(str(len(rotulos))), _largura_contagem(matriz))
    # Blocos equilibrados: duas colunas sobrando no último bloco leem pior que
    # blocos de tamanho parecido.
    cabem = max(1, (largura_terminal - largura_rotulo) // (largura_celula + 2))
    blocos = ceil(len(rotulos) / cabem)
    por_bloco = ceil(len(rotulos) / blocos)

    console.rule("[bold]Erros por rótulo (real × previsto)[/bold]")
    for inicio in range(0, len(rotulos), por_bloco):
        colunas = range(inicio, min(inicio + por_bloco, len(rotulos)))
        tabela = Table(box=None, pad_edge=False, padding=(0, 1, 0, 0))
        tabela.add_column(f"{'real \\ prev':<{largura_rotulo}}", no_wrap=True)
        for j in colunas:
            tabela.add_column(
                f"[dim]{j}[/dim]", justify="right", width=largura_celula, no_wrap=True
            )
        for i, rotulo in enumerate(rotulos):
            maximo = max(matriz[i]) or 1
            tabela.add_row(
                Text.assemble(
                    (f"{i:>2} {rotulo} ", ""), (f"({sum(matriz[i])})", "dim")
                ),
                *[_celula(matriz[i][j], maximo) for j in colunas],
            )
        console.print(tabela)
    console.print(
        "[dim]A diagonal (acerto) fica fora: cada linha mostra só os erros "
        + "daquele rótulo real, o fundo acompanha a fração do maior deles "
        + "(k = milhares) e o total está entre parênteses.[/dim]"
    )


def avaliar(
    teste: Exemplos,
    crf: sklearn_crfsuite.CRF,
    treino: Exemplos | None = None,
    nome: str | None = None,
) -> None:
    """Relatorio completo do recorte de teste, com o treino como referencia."""
    desempenho_treino = None
    if treino is None:
        console.print("[dim]Prevendo o recorte de teste...[/dim]")
    else:
        console.print("[dim]Prevendo os recortes de treino e teste...[/dim]")
        desempenho_treino = medir(treino.y, _prever(crf, treino.x))
    avaliar_previsto(teste, _prever(crf, teste.x), desempenho_treino, nome)


def avaliar_previsto(
    teste: Exemplos,
    previsto: Rotulos,
    desempenho_treino: Desempenho | None = None,
    nome: str | None = None,
) -> None:
    """Relatorio do recorte a partir de rotulos ja previstos.

    Existe para a validacao cruzada: ali cada exemplo foi previsto por um modelo
    diferente, entao nao ha um `crf` unico para consultar. Sem `desempenho_treino`
    sai sem a coluna de treino (e sem a suspeita de vazamento, que so faz sentido
    quando existe um treino unico).
    """
    titulo = "Avaliacao do CRF" if nome is None else f"Avaliacao do CRF — {nome}"
    console.rule(f"[bold]{titulo}[/bold]")
    _cabecalho(desempenho_treino, medir(teste.y, previsto))

    _por_rotulo(teste.y, previsto)
    _por_categoria(teste, previsto)
    imprimir_erros_por_rotulo(teste.y, previsto)
    _tokens_mais_errados(teste.x, teste.y, previsto)
