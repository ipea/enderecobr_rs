"""CRF de enderecos: dados de treino, treino, tuning e inferencia."""

from __future__ import annotations

import random
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import sklearn_crfsuite
import typer
from sklearn.metrics import make_scorer
from sklearn.model_selection import (
    GridSearchCV,
    KFold,
    StratifiedKFold,
    train_test_split,
)

from crf_endereco.config import CAMINHO_DATASET, CAMINHO_TAGGER
from crf_endereco.dataset import (
    abrir_banco,
    calcular_hash,
    carregar_anotados,
    gravar_recorte,
    ler_recorte,
    segmentos_de,
)
from crf_endereco.features import (
    ExtratorFeature,
    is_pontuacao,
    tokenize,
    tokenize_com_offsets,
)
from crf_endereco.modelo import relatorio
from crf_endereco.rotulos import alinhamento
from crf_endereco.ui import console

# `str.isspace()` e mais amplo que o `u8::is_ascii_whitespace` usado pelo Rust
# (inclui NBSP, por exemplo); o conjunto explicito mantem as duas
# implementacoes equivalentes.
ESPACOS_ASCII = frozenset(" \t\n\x0c\r")

# Como separar treino e teste. Estrategia `origem`: garante que toda origem
# apareca dos dois lados (67% do corpus vem de tres origens, entao um split
# aleatorio pode deixar uma delas inteira fora do teste).
ESTRATIFICACOES = ("origem", "origem_uf", "nenhum")

# Grade e orcamento de `tunar`; a CLI expoe cada um destes valores como opcao.
GRADE_C1: list[float] = [0.0, 0.01, 0.1, 0.25]
GRADE_C2: list[float] = [0.1, 0.25, 0.5, 1.0]
MAX_ITERACOES_TUNING = 500
MIN_FREQ_TUNING = 3
N_JOBS_TUNING = 13
SEMENTE_TUNING = 42
FRACAO_VALIDACAO_TUNING = 0.1
VERBOSE_TUNING = 3

# Hiperparametros fixos do modelo que vai para o tagger (o `tunar` so sugere).
C1_TREINO = 0.1
C2_TREINO = 0.2
MAX_ITERACOES_TREINO = 5_000
MIN_FREQ_TREINO = 2
VERBOSE_TREINO = True
# Semente do split treino/teste: o `tunar` usa a mesma para que o score da busca
# seja comparavel ao do modelo final.
SEMENTE_SPLIT = 42
# Semente das variantes de `aumentar`: o mesmo dataset gera o mesmo treino.
SEMENTE_AUMENTO = 7
DIGITOS = "0123456789"

# Folds do `avaliar --kfold`. Com ~9 mil exemplos, tres folds ja poem o
# erro-padrao do endereco perfeito perto de meio ponto percentual (com os 10% de
# teste do split fixo fica em ~1,5pp, maior do que as melhorias que interessam).
FOLDS_VALIDACAO = 3


@dataclass(frozen=True)
class Exemplos:
    """Dataset pronto para o CRF: features, rotulos, tokens e categorias.

    `hashes` e a chave do endereco no banco (`hash_endereco`): e por ela que o
    recorte gravado no treino identifica cada linha.
    """

    x: list[list[dict[str, float]]]
    y: list[list[str]]
    tokens: list[list[str]]
    categorias: list[list[str]]
    hashes: list[str]


def alvo_vazio(labels: Sequence[str]) -> bool:
    """Endereco cujo alvo ficou todo `O`: nada que o modelo possa aprender.

    Acontece com resposta sem segmento nenhum (falha de anotacao) e com o
    endereco que so tem trecho descartado (`ruido`, `outros`, `cadastro`). No
    treino nao ensina nada e no teste cobra o acerto de uma linha que nao tem
    resposta: fica de fora dos dois lados.
    """
    return all(label == "O" for label in labels)


def carregar_exemplos(caminho: Path = CAMINHO_DATASET) -> Exemplos:
    """Le o dataset etiquetado e monta features/rotulos.

    E o unico caminho de dados do modelo: treino, busca de hiperparametros e
    avaliacao usam exatamente as mesmas linhas, features e etiquetas.
    """
    extrator = ExtratorFeature()
    x: list[list[dict[str, float]]] = []
    y: list[list[str]] = []
    tokens: list[list[str]] = []
    categorias: list[list[str]] = []
    hashes: list[str] = []
    descartados_sem_alvo = 0
    descartados_desalinhados = 0

    console.print("[dim]Preprocessando dados...[/dim]")
    for exemplo in carregar_anotados(caminho):
        toks, labels, residuo = alinhamento(
            exemplo.endereco, segmentos_de(exemplo), tokenize
        )
        if alvo_vazio(labels):
            descartados_sem_alvo += 1
            continue
        if residuo:
            descartados_desalinhados += 1
            continue
        x.append(extrator.tokens2features(toks))
        y.append(labels)
        tokens.append(toks)
        categorias.append([exemplo.origem, exemplo.uf])
        hashes.append(calcular_hash(exemplo.endereco))

    if descartados_sem_alvo:
        console.print(
            f"[dim]Descartados {descartados_sem_alvo} enderecos sem alvo "
            + "(resposta vazia ou so com trecho descartado)[/dim]"
        )
    if descartados_desalinhados:
        console.print(
            f"[dim]Descartados {descartados_desalinhados} enderecos com trecho que "
            + "nao casa com token (palavra colada na base de origem)[/dim]"
        )
    return Exemplos(x=x, y=y, tokens=tokens, categorias=categorias, hashes=hashes)


def _chaves_estratificacao(exemplos: Exemplos, por: str) -> list[str] | None:
    """Chave de estratificacao por exemplo (`None` desliga o estrato)."""
    if por not in ESTRATIFICACOES:
        raise ValueError(f"estratificacao invalida: {por} (use {ESTRATIFICACOES})")
    if por == "nenhum":
        return None
    if por == "origem_uf":
        return [f"{categoria[0]}|{categoria[1]}" for categoria in exemplos.categorias]
    return [categoria[0] for categoria in exemplos.categorias]


def _indices_folds(
    exemplos: Exemplos, folds: int, semente: int, estratificar_por: str
) -> list[tuple[list[int], list[int]]]:
    """Folds estratificados: cada exemplo fica de fora do modelo que o preve."""
    if folds < 2:
        raise typer.BadParameter(f"kfold precisa de pelo menos 2 folds (pedido: {folds})")
    chaves = _chaves_estratificacao(exemplos, estratificar_por)
    indices = list(range(len(exemplos.y)))
    if chaves is None:
        # `StratifiedKFold` exige as chaves: sem estrato, o sorteio e o simples.
        simples = KFold(n_splits=folds, shuffle=True, random_state=semente)
        return [(list(treino), list(teste)) for treino, teste in simples.split(indices)]
    estratificado = StratifiedKFold(n_splits=folds, shuffle=True, random_state=semente)
    return [
        (list(treino), list(teste))
        for treino, teste in estratificado.split(indices, chaves)
    ]


def _recortar(exemplos: Exemplos, indices: Sequence[int]) -> Exemplos:
    """Subconjunto de `Exemplos`, preservando a ordem original."""
    ordenados = sorted(indices)
    return Exemplos(
        x=[exemplos.x[i] for i in ordenados],
        y=[exemplos.y[i] for i in ordenados],
        tokens=[exemplos.tokens[i] for i in ordenados],
        categorias=[exemplos.categorias[i] for i in ordenados],
        hashes=[exemplos.hashes[i] for i in ordenados],
    )


def _indices_split(
    exemplos: Exemplos,
    fracao_teste: float,
    semente: int,
    estratificar_por: str,
) -> tuple[list[int], list[int]]:
    """Indices de treino e teste de um split reproduzivel e estratificado."""
    chaves = _chaves_estratificacao(exemplos, estratificar_por)
    indices = list(range(len(exemplos.y)))
    treino, teste = train_test_split(
        indices, test_size=fracao_teste, random_state=semente, stratify=chaves
    )
    return list(treino), list(teste)


def dividir(
    exemplos: Exemplos,
    fracao_teste: float = 0.1,
    semente: int = SEMENTE_SPLIT,
    estratificar_por: str = "origem",
) -> tuple[Exemplos, Exemplos]:
    """Separa treino e teste de forma reproduzivel e estratificada.

    O mesmo par (semente, estratificacao) reproduz o split em `treinar` e em
    `avaliar`, entao a avaliacao nunca cai no dataset inteiro.
    """
    treino, teste = _indices_split(exemplos, fracao_teste, semente, estratificar_por)
    return _recortar(exemplos, treino), _recortar(exemplos, teste)


def _sem_pontuacao(
    toks: Sequence[str], labels: Sequence[str]
) -> tuple[list[str], list[str]] | None:
    """Exemplo sem a pontuação que pode sair sem emendar dois trechos.

    Sai a pontuação de dentro de um trecho (`S/N`) e a que separa trechos de
    tipos diferentes. Fica a que separa dois trechos do mesmo tipo
    (`GLEBA 1, LOTE 2`): sem ela a emenda entre os dois viraria uma sequência de
    rótulos ambígua.
    """
    # Tipo do trecho imediatamente antes e depois de cada token.
    antes: list[str | None] = []
    tipo = None
    for label in labels:
        antes.append(tipo)
        if label != "O":
            tipo = label.partition("_")[2]

    depois: list[str | None] = [None] * len(labels)
    tipo = None
    for i in range(len(labels) - 1, -1, -1):
        depois[i] = tipo
        if labels[i] != "O":
            tipo = labels[i].partition("_")[2]

    toks_sem: list[str] = []
    labels_sem: list[str] = []
    for tok, label, tipo_antes, tipo_depois in zip(
        toks, labels, antes, depois, strict=True
    ):
        fica = label == "O" and tipo_antes is not None and tipo_antes == tipo_depois
        if is_pontuacao(tok) and not fica:
            continue
        toks_sem.append(tok)
        labels_sem.append(label)

    return None if toks_sem == list(toks) else (toks_sem, labels_sem)


def _sem_cabeca(
    toks: Sequence[str], labels: Sequence[str]
) -> tuple[list[str], list[str]] | None:
    """Exemplo sem o trecho `O` que abre o texto (`Q SQN 404 BLOCO G 101`).

    O `Q` nao e do endereco: e codigo da base de origem, e no uso real o texto
    comeca no `SQN`. O rotulo do trecho e `O` justamente por nao pertencer a
    segmento nenhum, entao tira-lo nao mexe no alvo (o resto e que define a
    segmentacao); o original continua no treino, porque o `Q` quando aparece
    tem que sair como `O` tambem.
    """
    inicio = 0
    while inicio < len(toks) and labels[inicio] == "O":
        inicio += 1
    if inicio == 0 or inicio == len(toks):
        return None
    return list(toks[inicio:]), list(labels[inicio:])


def _numeros_trocados(
    toks: Sequence[str], labels: Sequence[str], rng: random.Random
) -> tuple[list[str], list[str]] | None:
    """Exemplo com cada digito trocado por outro, mantendo tamano e separadores.

    O valor de um numero nao define o tipo do trecho: sem variar, o modelo pode
    usar o `404` de `SQN 404` como pista e memorizar o numero (`BLOCO G` com
    `101` de numero, `302` de parcela). Trocados os digitos, sobra a forma
    (grupos, hifen, letra colada), que e o sinal legitimo.
    """
    trocados = [
        "".join(rng.choice(DIGITOS) if c.isdigit() else c for c in tok) for tok in toks
    ]
    if trocados == list(toks):
        return None
    return trocados, list(labels)


def _variantes(
    toks: Sequence[str], labels: Sequence[str], rng: random.Random
) -> list[tuple[list[str], list[str]]]:
    """Formas alternativas do mesmo exemplo, todas com o alvo original."""
    variantes = []
    for variante in (
        _sem_pontuacao(toks, labels),
        _sem_cabeca(toks, labels),
        _numeros_trocados(toks, labels, rng),
    ):
        if variante is not None:
            variantes.append(variante)
    return variantes


def aumentar(exemplos: Exemplos) -> Exemplos:
    """Acrescenta as variantes de cada exemplo (sem pontuacao, sem cabeca, numeros).

    O objetivo e o que *nao* e pista: a pontuacao vai e volta no uso real, o
    codigo `O` que abre o texto da base nao aparece, e o valor do numero nao
    muda o tipo do trecho. A variante herda o hash do original, entao ela nunca
    vira um exemplo do teste — so o treino aumenta.
    """
    extrator = ExtratorFeature()
    rng = random.Random(SEMENTE_AUMENTO)
    x = list(exemplos.x)
    y = list(exemplos.y)
    tokens = list(exemplos.tokens)
    categorias = list(exemplos.categorias)
    hashes = list(exemplos.hashes)

    for toks, labels, categoria, hash_ in zip(
        exemplos.tokens, exemplos.y, exemplos.categorias, exemplos.hashes, strict=True
    ):
        for toks_novos, labels_novos in _variantes(toks, labels, rng):
            x.append(extrator.tokens2features(toks_novos))
            y.append(labels_novos)
            tokens.append(toks_novos)
            categorias.append(categoria)
            hashes.append(hash_)

    return Exemplos(x=x, y=y, tokens=tokens, categorias=categorias, hashes=hashes)


def nome_do_modelo(tagger: Path) -> str:
    """Nome com que o banco identifica o recorte de um tagger."""
    return tagger.stem


def separar_por_recorte(
    exemplos: Exemplos, recorte: dict[str, set[str]]
) -> tuple[Exemplos, Exemplos]:
    """Treino e teste de `exemplos` conforme os hashes gravados no banco."""
    treino = [
        i for i, hash_ in enumerate(exemplos.hashes) if hash_ in recorte["treino"]
    ]
    teste = [i for i, hash_ in enumerate(exemplos.hashes) if hash_ in recorte["teste"]]
    return _recortar(exemplos, treino), _recortar(exemplos, teste)


def recorte_gravado(
    tagger: Path = CAMINHO_TAGGER, dataset: Path = CAMINHO_DATASET
) -> tuple[Exemplos, Exemplos]:
    """Treino e teste conforme o recorte que o `treinar` gravou no banco.

    O split nao e recalculado: sem saber quais enderecos o modelo viu, medir no
    dataset inteiro viraria vazamento disfarcado de acuracia.
    """
    exemplos = carregar_exemplos(dataset)
    conn = abrir_banco(dataset)
    try:
        recorte = ler_recorte(conn, nome_do_modelo(tagger))
    finally:
        conn.close()

    if not recorte["treino"] or not recorte["teste"]:
        raise typer.BadParameter(
            f"recorte nao gravado para {tagger.name}: treine com `crf treinar`.\n"
            + "Sem o recorte nao da para saber o que o modelo ja viu."
        )

    treino, teste = separar_por_recorte(exemplos, recorte)
    if not teste.y:
        raise typer.BadParameter(
            f"nenhum endereco do recorte de teste de {tagger.name} esta no banco."
        )
    return treino, teste


def treinar(
    dataset: Path = CAMINHO_DATASET,
    saida: Path = CAMINHO_TAGGER,
    fracao_teste: float = 0.1,
    estratificar_por: str = "origem",
    com_aumento: bool = False,
    c1: float = C1_TREINO,
    c2: float = C2_TREINO,
    max_iteracoes: int = MAX_ITERACOES_TREINO,
    min_freq: int = MIN_FREQ_TREINO,
    verboso: bool = VERBOSE_TREINO,
    semente: int = SEMENTE_SPLIT,
) -> None:
    """Treina o CRF e reporta a acuracia na fracao de teste."""
    exemplos = carregar_exemplos(dataset)
    treino, teste = dividir(
        exemplos, fracao_teste, semente, estratificar_por=estratificar_por
    )
    # Gravado antes do aumento: as variantes sem pontuacao nao sao enderecos do
    # banco e nao podem virar elo entre treino e teste.
    conn = abrir_banco(dataset)
    try:
        gravar_recorte(conn, nome_do_modelo(saida), treino.hashes, teste.hashes)
    finally:
        conn.close()
    if com_aumento:
        # Só o treino aumenta: a variante de um exemplo no teste vazaria a
        # resposta dele para o modelo.
        original = len(treino.y)
        treino = aumentar(treino)
        console.print(
            f"[dim]Aumento: {len(treino.y) - original} variantes "
            + "(sem pontuacao, sem cabeca, numeros trocados)[/dim]"
        )
    composicao = Counter(categoria[0] for categoria in teste.categorias)
    console.print(
        f"[dim]Treino: {len(treino.y)} | teste: {len(teste.y)} "
        + f"(estratificado por {estratificar_por}) "
        + f"| teste por origem: {dict(composicao.most_common())}[/dim]"
    )

    console.print(f"[dim]Treinando (n={len(treino.y)})...[/dim]")
    saida.parent.mkdir(parents=True, exist_ok=True)
    crf = _novo_crf(c1, c2, max_iteracoes, min_freq, verboso, saida)
    modelo = crf.fit(treino.x, treino.y)
    # O treino acabou de ver estes exemplos: o relatorio aqui so mede o teste,
    # e a comparacao treino x teste fica para o `crf avaliar`.
    relatorio.avaliar(teste, modelo, nome=saida.name)


def _novo_crf(
    c1: float = C1_TREINO,
    c2: float = C2_TREINO,
    max_iteracoes: int = MAX_ITERACOES_TREINO,
    min_freq: int = MIN_FREQ_TREINO,
    verboso: bool = VERBOSE_TREINO,
    modelo: Path | None = None,
) -> sklearn_crfsuite.CRF:
    """CRF com os hiperparametros do tagger, com ou sem arquivo de saida."""
    return sklearn_crfsuite.CRF(
        algorithm="lbfgs",
        c1=c1,
        c2=c2,
        verbose=verboso,
        max_iterations=max_iteracoes,
        all_possible_transitions=False,
        all_possible_states=False,
        min_freq=min_freq,
        model_filename=None if modelo is None else str(modelo),
    )


def validacao_cruzada(
    exemplos: Exemplos,
    folds: int = FOLDS_VALIDACAO,
    semente: int = SEMENTE_SPLIT,
    estratificar_por: str = "origem",
    com_aumento: bool = False,
    c1: float = C1_TREINO,
    c2: float = C2_TREINO,
) -> list[list[str]]:
    """Rotulos de cada exemplo previstos por um modelo que nao o viu.

    Cada endereco e previsto pelo fold inteiro que o excluiu do treino, entao o
    recorte de avaliacao deixa de ser uma amostra de 10%: a media passa a usar
    o dataset inteiro e o erro-padrao desaba junto. O preco e treinar `folds`
    modelos em vez de carregar um tagger pronto.

    `com_aumento` aumenta so o treino de cada fold: as variantes de um exemplo
    do teste caíriam dentro do treino e o modelo veria a resposta dele.
    """
    previsto: list[list[str]] = [[] for _ in exemplos.y]
    for numero, (treino, teste) in enumerate(
        _indices_folds(exemplos, folds, semente, estratificar_por), start=1
    ):
        console.print(f"[dim]Fold {numero}/{folds}: treinando com {len(treino)}...[/dim]")
        conjunto = _recortar(exemplos, treino)
        if com_aumento:
            conjunto = aumentar(conjunto)
            console.print(f"[dim]  aumento: {len(conjunto.y)} exemplos[/dim]")
        crf = _novo_crf(c1=c1, c2=c2, verboso=False)
        crf.fit(conjunto.x, conjunto.y)
        for i, tags in zip(
            teste, crf.predict([exemplos.x[i] for i in teste]), strict=True
        ):
            previsto[i] = [str(tag) for tag in tags]
    return previsto


def enderecos_exatos(y_verdadeiro: list[list[str]], y_previsto: list[list[str]]) -> float:
    """Fracao de enderecos com todos os rotulos certos: a metrica do uso real.

    A busca de hiperparametros usava acerto de token (`flat_accuracy_score`),
    que premia acertar tokens faceis e nao ve o endereco que sai errado por um
    unico token — o alvo do ajuste e o endereco inteiro.
    """
    return sum(
        1
        for real, previsto in zip(y_verdadeiro, y_previsto, strict=True)
        if list(real) == list(previsto)
    ) / len(y_verdadeiro)


def tunar(
    c1: Sequence[float] = GRADE_C1,
    c2: Sequence[float] = GRADE_C2,
    max_iteracoes: int = MAX_ITERACOES_TUNING,
    min_freq: int = MIN_FREQ_TUNING,
    n_jobs: int = N_JOBS_TUNING,
    semente: int = SEMENTE_TUNING,
    fracao_validacao: float = FRACAO_VALIDACAO_TUNING,
    verboso: int = VERBOSE_TUNING,
    com_aumento: bool = False,
    estratificar_por: str = "origem",
) -> None:
    """Busca de hiperparametros sobre o mesmo dataset, features e etiquetas.

    A validacao usa o mesmo split de `treinar`/`avaliar` (fracao, semente e
    estratificacao), entao o score da busca e comparavel ao do modelo final.
    ``com_aumento`` desligado por padrao: as variantes de um exemplo cairiam dos
    dois lados dos folds da validacao cruzada.
    """
    exemplos = carregar_exemplos()
    treino_idx, validacao_idx = _indices_split(
        exemplos, fracao_validacao, semente, estratificar_por
    )
    treino = _recortar(exemplos, treino_idx)
    validacao = _recortar(exemplos, validacao_idx)
    if com_aumento:
        original = len(treino.y)
        treino = aumentar(treino)
        console.print(
            f"[dim]Aumento: {len(treino.y) - original} variantes "
            + "(sem pontuacao, sem cabeca, numeros trocados)[/dim]"
        )
    # A validacao sao os exemplos originais: variante de um deles no treino
    # vazaria a resposta para a busca.
    x = treino.x + validacao.x
    y = treino.y + validacao.y
    corte = len(treino.y)
    folds = [(list(range(corte)), list(range(corte, len(y))))]
    crf = sklearn_crfsuite.CRF(
        algorithm="lbfgs",
        max_iterations=max_iteracoes,
        all_possible_transitions=True,
        all_possible_states=True,
        min_freq=min_freq,
        verbose=False,
    )
    busca = GridSearchCV(
        crf,
        param_grid={"c1": list(c1), "c2": list(c2)},
        cv=folds,
        verbose=verboso,
        n_jobs=n_jobs,
        scoring=make_scorer(enderecos_exatos),
        refit=True,
    )
    _ = busca.fit(x, y)

    tamanho = (busca.best_estimator_.size_ or 0) / 1_000_000
    console.print(f"melhores parametros: {busca.best_params_}")
    console.print(f"[dim]endereco perfeito na validacao: {busca.best_score_:.4f}[/dim]")
    console.print(f"[dim]tamanho do modelo: {tamanho:0.2f}M[/dim]")
    # O ranking inteiro: a validacao tem ~1.100 enderecos, entao o topo da lista
    # pode ser sorteio — ver o vizinho de parametro que pontua igual e o que
    # permite escolher por tamanho sem perder qualidade.
    resultados = busca.cv_results_
    ranking: list[tuple[float, dict[str, float]]] = sorted(
        zip(
            (float(nota) for nota in resultados["mean_test_score"]),
            resultados["params"],
            strict=True,
        ),
        key=lambda par: par[0],
        reverse=True,
    )
    ordenados = ranking
    console.print("[dim]ranking (c1, c2, endereco perfeito):[/dim]")
    for score, params in ordenados:
        console.print(f"[dim]  {params['c1']:>5} {params['c2']:>5} {score:.4f}[/dim]")


def carregar_tagger(caminho: Path = CAMINHO_TAGGER) -> sklearn_crfsuite.CRF:
    """Carrega o CRF treinado, com erro claro quando o arquivo nao existe."""
    if not caminho.is_file():
        raise typer.BadParameter(
            f"tagger nao encontrado: {caminho}\n"
            + "treine com `uv run crf treinar` ou passe --tagger"
        )
    return sklearn_crfsuite.CRF(model_filename=str(caminho))


def montar_segmentos(
    frase: str,
    tokens_com_offset: list[tuple[str, int]],
    tags: list[str],
) -> list[dict[str, str]]:
    """Remonta os segmentos a partir dos rotulos BIO.

    Espelha `SeparadorEndereco::segmentar` do Rust (`src/separador_endereco.rs`):
    o separador entre tokens de um mesmo segmento vem do texto bruto, ou seja,
    so entra um espaco quando o caractere anterior ao token e espaco em branco.
    Assim "S/N" e "310A" continuam verbatim em vez de virar "S / N" e "310 A".
    """
    segmentos: list[dict[str, str]] = []

    for (tok, offset), tag in zip(tokens_com_offset, tags, strict=True):
        partes = tag.split("_", 1)
        if len(partes) != 2:
            continue  # "O": token fora de qualquer segmento

        bio, tipo = partes
        tipo = tipo.lower()

        if bio == "B":
            segmentos.append({"tipo": tipo, "valor": tok})
        elif bio == "I":
            if not segmentos or segmentos[-1]["tipo"] != tipo:
                continue
            if offset > 0 and frase[offset - 1] in ESPACOS_ASCII:
                segmentos[-1]["valor"] += " "
            segmentos[-1]["valor"] += tok

    return segmentos


def segmentar(
    crf: sklearn_crfsuite.CRF, extrator: ExtratorFeature, frase: str
) -> list[dict[str, str]]:
    """Pipeline completo do Rust (`segmentar_endereco`) para uma frase."""
    tokens_com_offset = tokenize_com_offsets(frase)
    x = extrator.tokens2features([tok for tok, _ in tokens_com_offset])
    tags = crf.predict_single(x)

    return montar_segmentos(frase, tokens_com_offset, tags)
