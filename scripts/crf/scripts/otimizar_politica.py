"""Politica declarativa pos-CRF, otimizada contra o CNEFE e a metrica de comparacao.py.

Contexto
--------
`segmento_como_endereco` decide em que campo do `Endereco` cada tipo da
ontologia (src/crf_endereco/anotacao/ontologia.py) cai. Aqui essa decisao e
tratada como dado — uma celula por tipo:

    Celula(papel, quando, se_preenchido)

e a tabela e otimizada por hill climbing (coordinate ascent) contra a metrica
de `geocode/comparacao.py`, medindo o delta em linhas pareadas. O achado, a
justificativa e os proximos passos estao em docs/politica_pos_crf.md.

Metrica
-------
`score_original` reproduz comparacao.py como esta hoje: o universo de
categorias e o das categorias *observadas*, entao o score muda so porque uma
categoria desapareceu. `score_fixo` usa o universo fixo (28 tipos de
tipo_resultado + "(sem)"), que e o que torna duas politicas comparaveis.

A escada de etapas implementada aqui e uma aproximacao local da do geocodebr
(chaves estado+municipio+logradouro+numero+cep+localidade): nao modela as
etapas probabilisticas pn*/pl* (Jaro) nem o desempate, logo os valores
absolutos NAO sao comparaveis com `crf geocode comparar`. Os deltas pareados
sao, e e por isso que a busca usa delta pareado e nao a diferenca de scores.

Custo
-----
O resultado do geocodebr depende so da tupla de chaves de cada linha, entao o
cache por tupla (CNEFE local) reduz cada varredura a O(n) lookups: 300k linhas
e ~800k tuplas convergem em ~70s.

Uso
---
    uv run python scripts/otimizar_politica.py --n 300000
    uv run python scripts/otimizar_politica.py --politica otimizada --sal holdout
    make otimizar N=300000

Toda execucao grava data/politicas/<nome>.json (politica + relatorio + traco
das varreduras); execucoes repetidas no mesmo nome acumulam em `historico`.
"""

from __future__ import annotations

import argparse
import collections
import json
import math
import re
import time
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from collections.abc import Iterable
from pathlib import Path

import duckdb
import enderecobr
import numpy as np
import pyarrow as pa

from crf_endereco.anotacao.ontologia import TIPOS_SEGMENTO
from crf_endereco.config import DIR_DADOS, DIR_REPO
from crf_endereco.features import ExtratorFeature
from crf_endereco.modelo import crf as modelo_crf

BASE_PADRAO = DIR_REPO / "aaaa.parquet"
PASTA_POLITICAS = DIR_DADOS / "politicas"
DADOS_CNEFE = Path.home() / ".cache" / "geocodebr" / "geocodebr_data_release_v0.5.0"
CNEFE_NUM = str(DADOS_CNEFE / "municipio_logradouro_numero_localidade.parquet")
CNEFE_LOGR = str(DADOS_CNEFE / "municipio_logradouro_localidade.parquet")
CNEFE_LOC = str(DADOS_CNEFE / "municipio_localidade.parquet")
CNEFE_CEP = str(DADOS_CNEFE / "municipio_cep.parquet")

ORDEM = (
    "dn01", "dn02", "dn03", "dn04", "pn01", "pn02", "pn03", "pn04",
    "da01", "da02", "da03", "da04", "pa01", "pa02", "pa03", "pa04",
    "dl01", "dl02", "dl03", "dl04", "pl01", "pl02", "pl03", "pl04",
    "dc01", "dc02", "db01", "dm01",
)
SEM_RESULTADO = "(sem)"
ETAPAS = (*ORDEM, SEM_RESULTADO)
PESO = {etapa: (len(ETAPAS) - i) / len(ETAPAS) for i, etapa in enumerate(ETAPAS)}


class Papel(StrEnum):
    """Campo do `Endereco` que recebe o valor do segmento."""

    LOGRADOURO = "logradouro"
    NUMERO = "numero"
    COMPLEMENTO = "complemento"
    LOCALIDADE = "localidade"
    CEP = "cep"
    DESCARTAR = "descartar"


class Quando(StrEnum):
    """Condicao para o segmento entrar no papel."""

    SEMPRE = "sempre"
    CAMPO_VAZIO = "vazio"
    APOS = "apos"
    SOZINHO = "sozinho"


class SePreenchido(StrEnum):
    """O que fazer quando o campo de destino ja tem valor."""

    JUNTAR = "juntar"
    IR_PARA_COMPLEMENTO = "complemento"
    IGNORAR = "ignorar"


@dataclass(frozen=True)
class Celula:
    """Destino de um tipo de segmento, com a condicao e o desempate."""

    papel: Papel
    quando: Quando = Quando.SEMPRE
    alvo: str = ""
    se_preenchido: SePreenchido = SePreenchido.JUNTAR

    @classmethod
    def de_dict(cls, dados: dict[str, str]) -> Celula:
        try:
            return cls(
                papel=Papel(dados["papel"]),
                quando=Quando(dados.get("quando", Quando.SEMPRE)),
                alvo=dados.get("alvo", ""),
                se_preenchido=SePreenchido(dados.get("se_preenchido", SePreenchido.JUNTAR)),
            )
        except KeyError as erro:
            raise SystemExit(f"celula sem campo obrigatorio: {erro}") from erro
        except ValueError as erro:
            raise SystemExit(f"valor invalido em celula: {erro}") from erro


Politica = dict[str, Celula]
Tupla = tuple[str, str | None, int | None, str | None]

DESCARTAR = Celula(Papel.DESCARTAR)


# A tabela e o artefato central: cada linha diz, para um tipo da ontologia, em
# que campo o valor entra, em que condicao e o que fazer se o campo ja tem valor.
INICIO: Politica = {
    "logradouro":       Celula(Papel.LOGRADOURO, Quando.CAMPO_VAZIO),
    "numero":           Celula(Papel.NUMERO),
    "complemento":      Celula(Papel.COMPLEMENTO),
    "parcela":          Celula(Papel.LOGRADOURO, Quando.APOS, alvo="logradouro"),
    "empreendimento":   Celula(Papel.LOCALIDADE, Quando.CAMPO_VAZIO),
    "localidade":       Celula(Papel.LOCALIDADE),
    "nucleo_rural":     Celula(Papel.LOCALIDADE),
    "recurso_natural":  DESCARTAR,
    "referencia":       DESCARTAR,
    "ponto_referencia": DESCARTAR,
    "denominacao":      DESCARTAR,
    "quilometragem_via": Celula(Papel.NUMERO, Quando.CAMPO_VAZIO),
    "cep":              Celula(Papel.CEP),
    "municipio":        DESCARTAR,
    "uf":               DESCARTAR,
    "cadastro":         DESCARTAR,
    "ruido":            DESCARTAR,
    "outros":           DESCARTAR,
}

# Vizinhas de cada celula: a busca testa uma troca de cada vez, so entre estas.
ALTERNATIVAS: dict[str, list[Celula]] = {
    "logradouro": [
        Celula(Papel.LOGRADOURO),
        Celula(Papel.COMPLEMENTO),
        DESCARTAR,
    ],
    "numero": [
        Celula(Papel.NUMERO, se_preenchido=SePreenchido.IR_PARA_COMPLEMENTO),
        Celula(Papel.NUMERO, Quando.CAMPO_VAZIO),
        Celula(Papel.COMPLEMENTO),
        DESCARTAR,
    ],
    "complemento": [
        DESCARTAR,
    ],
    "parcela": [
        Celula(Papel.COMPLEMENTO),
        Celula(Papel.NUMERO, Quando.CAMPO_VAZIO),
        Celula(Papel.LOCALIDADE),
        Celula(Papel.LOGRADOURO),
        DESCARTAR,
    ],
    "empreendimento": [
        Celula(Papel.LOCALIDADE),
        Celula(Papel.COMPLEMENTO),
        Celula(Papel.LOGRADOURO, Quando.SOZINHO),
        DESCARTAR,
    ],
    "localidade": [
        DESCARTAR,
    ],
    "nucleo_rural": [
        Celula(Papel.LOCALIDADE, Quando.CAMPO_VAZIO),
        Celula(Papel.COMPLEMENTO),
        Celula(Papel.LOGRADOURO, Quando.SOZINHO),
        DESCARTAR,
    ],
    "recurso_natural": [
        Celula(Papel.LOCALIDADE),
        Celula(Papel.COMPLEMENTO),
        Celula(Papel.LOGRADOURO, Quando.SOZINHO),
        DESCARTAR,
    ],
    "quilometragem_via": [
        Celula(Papel.NUMERO),
        Celula(Papel.COMPLEMENTO),
        DESCARTAR,
    ],
    "cep": [],
    "referencia": [
        Celula(Papel.COMPLEMENTO),
        DESCARTAR,
    ],
    "ponto_referencia": [
        Celula(Papel.COMPLEMENTO),
        DESCARTAR,
    ],
    "denominacao": [
        Celula(Papel.COMPLEMENTO),
        Celula(Papel.LOGRADOURO),
        DESCARTAR,
    ],
    "cadastro": [
        Celula(Papel.COMPLEMENTO),
        DESCARTAR,
    ],
    "ruido": [
        Celula(Papel.COMPLEMENTO),
        DESCARTAR,
    ],
    "outros": [
        Celula(Papel.COMPLEMENTO),
        DESCARTAR,
    ],
    "municipio": [],
    "uf": [],
}


@dataclass
class Achado:
    """O que o CNEFE diz sobre as chaves de uma linha."""

    numero: bool = False
    localidade_confere: bool = False
    logradouro: bool = False
    localidade: bool = False


@dataclass
class Estado:
    """Amostra segmentada mais o cache CNEFE por tupla de chaves."""

    con: duckdb.DuckDBPyConnection
    segs: list[list[tuple[str, str]]]
    presentes: list[frozenset[str]]
    linhas_por_tipo: dict[str, list[int]]
    municipios: list[str]
    cep_confere: list[bool]
    cache: dict[Tupla, Achado] = field(default_factory=dict)

    def __len__(self) -> int:
        return len(self.municipios)


@dataclass
class Alteracao:
    """Uma celula aceita pela busca."""

    varredura: int
    tipo: str
    celula: Celula
    delta_pp: float


@dataclass
class Relatorio:
    """Resultado de uma execucao, comparavel entre amostras e politicas."""

    n: int
    tuplas_no_cache: int
    delta_pareado_pp: float
    ic95: tuple[float, float]
    score_fixo: tuple[float, float]
    ndcg_fixo: tuple[float, float]
    score_original: tuple[float, float]
    distribuicao_inicial: dict[str, int]
    distribuicao_final: dict[str, int]
    alteracoes: list[Alteracao]
    varreduras: list[list[tuple[str, Celula, float]]]


def cronometrar(rotulo: str, inicio: float) -> float:
    print(f"[{rotulo}] {time.perf_counter() - inicio:.1f}s", flush=True)
    return time.perf_counter()


def ler_json(caminho: Path) -> dict[str, object]:
    try:
        dados = json.loads(caminho.read_text())
    except (OSError, json.JSONDecodeError) as erro:
        raise SystemExit(f"falha ao ler {caminho}: {erro}") from erro
    if not isinstance(dados, dict):
        raise SystemExit(f"json invalido em {caminho}: esperado um objeto")
    return dados


def preparar_amostra(
    con: duckdb.DuckDBPyConnection, base: Path, n: int, sal: str
) -> tuple[list[tuple[str, str]], list[bool]]:
    """Sorteia `n` enderecos de forma reproduzivel e mede se o cep da base existe no municipio.

    O sorteio usa `hash(endereco + sal)` em vez de `using sample`, para que a
    mesma amostra volte sempre e `--sal` gere um holdout disjunto.
    """
    bruto = con.execute(
        'select count(*) from read_parquet(?) where "DscEndereco" is not null',
        [str(base)],
    ).fetchone()
    valor = bruto[0] if bruto is not None else None
    total = valor if isinstance(valor, int) else 0
    if total <= 0:
        raise SystemExit(f"base sem enderecos: {base}")
    taxa = max(1, min(999_999, round(1_000_000 * 10 * n / total)))
    con.execute(
        """
        create or replace temp table amostra as
        select row_number() over () - 1 as id, municipio, cep, "DscEndereco" as endereco
        from (
            select municipio, cep, "DscEndereco"
            from read_parquet(?)
            where "DscEndereco" is not null
              and hash(cep || '~' || "DscEndereco" || ?) % 1000000 < ?
            limit ?
        )
        """,
        [str(base), sal, taxa, n],
    )
    linhas = [
        (str(municipio), str(endereco))
        for municipio, endereco in con.execute(
            "select municipio, endereco from amostra order by id"
        ).fetchall()
    ]
    cep_confere = [
        bool(confere)
        for (confere,) in con.execute(
            """
            select c.municipio is not null
            from amostra a
            left join (select distinct municipio, cep from read_parquet(?)) c
              on c.municipio = a.municipio and c.cep = a.cep
            order by a.id
            """,
            [CNEFE_CEP],
        ).fetchall()
    ]
    return linhas, cep_confere


def segmentar(tagger: Path, enderecos: Iterable[str]) -> list[list[tuple[str, str]]]:
    """Segmenta com o CRF de Python, que e o mesmo modelo do binario Rust."""
    crf = modelo_crf.carregar_tagger(tagger)
    extrator = ExtratorFeature()
    lista = list(enderecos)
    pedaco, saida = 10000, []
    for inicio in range(0, len(lista), pedaco):
        for endereco in lista[inicio : inicio + pedaco]:
            saida.append(
                [(s["tipo"], s["valor"]) for s in modelo_crf.segmentar(crf, extrator, endereco)]
            )
        print(f"[segmentacao] {len(saida)}/{len(lista)}", flush=True)
    return saida


def criar_estado(args: argparse.Namespace) -> Estado:
    con = duckdb.connect()
    con.execute("set threads to 12")
    linhas, cep_confere = preparar_amostra(con, args.base, args.n, args.sal)
    segs = segmentar(args.tagger, [endereco for _, endereco in linhas])
    presentes = [frozenset(tipos for tipos, _ in s) for s in segs]
    linhas_por_tipo: dict[str, list[int]] = collections.defaultdict(list)
    for i, tipos in enumerate(presentes):
        for tipo in tipos:
            linhas_por_tipo[tipo].append(i)
    return Estado(
        con=con,
        segs=segs,
        presentes=presentes,
        linhas_por_tipo=dict(linhas_por_tipo),
        municipios=[municipio for municipio, _ in linhas],
        cep_confere=cep_confere,
    )


_MEMO_LOGRADOURO: dict[str, str | None] = {}
_MEMO_NUMERO: dict[str, int | None] = {}
_MEMO_LOCALIDADE: dict[str, str | None] = {}


def padronizar(valor: str, papel: Papel) -> str | int | None:
    """Padroniza o valor com o mesmo padronizador do campo de destino."""
    if papel is Papel.LOGRADOURO:
        if valor not in _MEMO_LOGRADOURO:
            _MEMO_LOGRADOURO[valor] = enderecobr.padronizar_logradouros(valor) or None
        return _MEMO_LOGRADOURO[valor]
    if papel is Papel.NUMERO:
        if valor not in _MEMO_NUMERO:
            _MEMO_NUMERO[valor] = enderecobr.padronizar_numeros_para_int(valor)
        return _MEMO_NUMERO[valor]
    if papel is Papel.LOCALIDADE:
        if valor not in _MEMO_LOCALIDADE:
            _MEMO_LOCALIDADE[valor] = enderecobr.padronizar_bairros(valor) or None
        return _MEMO_LOCALIDADE[valor]
    return valor


def donos_por_papel(pol: Politica, presentes: frozenset[str]) -> dict[Papel, set[str]]:
    """Tipos que disputam cada papel nesta linha: e o que `Quando.SOZINHO` consulta."""
    donos: dict[Papel, set[str]] = collections.defaultdict(set)
    for tipo in presentes:
        donos[pol[tipo].papel].add(tipo)
    return donos


def aceita(celula: Celula, tipo: str, anterior: Papel | None, campos: dict[Papel, str], donos: dict[Papel, set[str]]) -> Papel | None:
    """Papel efetivo do segmento, ou None quando a celula nao se aplica."""
    if celula.papel is Papel.DESCARTAR:
        return None
    if celula.quando is Quando.CAMPO_VAZIO and campos.get(celula.papel) is not None:
        return None
    if celula.quando is Quando.APOS and anterior != Papel(celula.alvo):
        return None
    if celula.quando is Quando.SOZINHO and not donos[celula.papel] <= {tipo}:
        return None
    return celula.papel


def aplicar(pol: Politica, segs: list[tuple[str, str]], presentes: frozenset[str]) -> dict[Papel, str]:
    """Monta os campos do `Endereco` a partir dos segmentos, segundo a politica."""
    campos: dict[Papel, str] = {}
    donos = donos_por_papel(pol, presentes)
    anterior: Papel | None = None
    for tipo, valor in segs:
        celula = pol[tipo]
        destino = aceita(celula, tipo, anterior, campos, donos)
        if destino is not None and campos.get(destino) is not None:
            if celula.se_preenchido is SePreenchido.IR_PARA_COMPLEMENTO and destino is not Papel.COMPLEMENTO:
                destino = Papel.COMPLEMENTO
            elif celula.se_preenchido is SePreenchido.IGNORAR:
                destino = None
        if destino is not None:
            atual = campos.get(destino)
            campos[destino] = valor if atual is None else f"{atual} {valor}"
        anterior = None if celula.papel is Papel.DESCARTAR else celula.papel
    return campos


def tupla(est: Estado, pol: Politica, i: int) -> Tupla:
    """Chave de busca no CNEFE para a linha `i` sob a politica dada."""
    campos = aplicar(pol, est.segs[i], est.presentes[i])
    logr = padronizar(campos[Papel.LOGRADOURO], Papel.LOGRADOURO) if Papel.LOGRADOURO in campos else None
    num = padronizar(campos[Papel.NUMERO], Papel.NUMERO) if Papel.NUMERO in campos else None
    loc = padronizar(campos[Papel.LOCALIDADE], Papel.LOCALIDADE) if Papel.LOCALIDADE in campos else None
    return (
        est.municipios[i],
        logr if isinstance(logr, str) else None,
        num if isinstance(num, int) else None,
        loc if isinstance(loc, str) else None,
    )


def como_tupla(municipio: object, logr: object, num: object, loc: object) -> Tupla:
    return (
        str(municipio),
        None if logr is None else str(logr),
        num if isinstance(num, int) else None,
        None if loc is None else str(loc),
    )


def _registrar(est: Estado, tuplas: list[Tupla]) -> None:
    est.con.register(
        "b",
        pa.table(
            {
                "municipio": pa.array([t[0] for t in tuplas]),
                "logradouro": pa.array([t[1] for t in tuplas]),
                "numero": pa.array([t[2] for t in tuplas], type=pa.int64()),
                "localidade": pa.array([t[3] for t in tuplas]),
            }
        ),
    )


class ChaveCnefe(StrEnum):
    """Conjunto de chaves do CNEFE que se consulta, do mais para o menos restrito."""

    NUMERO = "numero"
    LOGRADOURO = "logradouro"
    LOCALIDADE = "localidade"


PERGUNTAS: dict[ChaveCnefe, tuple[str, str]] = {
    ChaveCnefe.NUMERO: (
        CNEFE_NUM,
        """
        select b.municipio, b.logradouro, b.numero, b.localidade,
               bool_or(r.numero is not null) as achou_numero,
               bool_or(r.localidade = b.localidade) as localidade_confere
        from b
        left join read_parquet(?) r
          on r.municipio = b.municipio and r.logradouro = b.logradouro and r.numero = b.numero
        group by all
        """,
    ),
    ChaveCnefe.LOGRADOURO: (
        CNEFE_LOGR,
        """
        select b.municipio, b.logradouro, b.numero, b.localidade,
               bool_or(r.logradouro is not null) as achou_logradouro
        from b
        left join read_parquet(?) r
          on r.municipio = b.municipio and r.logradouro = b.logradouro
        group by all
        """,
    ),
    ChaveCnefe.LOCALIDADE: (
        CNEFE_LOC,
        """
        select b.municipio, b.logradouro, b.numero, b.localidade,
               bool_or(r.localidade is not null) as achou_localidade
        from b
        left join read_parquet(?) r
          on r.municipio = b.municipio and r.localidade = b.localidade
        group by all
        """,
    ),
}


def perguntar(est: Estado, tuplas: list[Tupla], chave: ChaveCnefe) -> list[tuple[object, ...]]:
    """Roda no CNEFE a pergunta `chave` para as tuplas e devolve chave + resposta."""
    parquet, consulta = PERGUNTAS[chave]
    _registrar(est, tuplas)
    return est.con.execute(consulta, [parquet]).fetchall()


def aquecer(est: Estado, tuplas: Iterable[Tupla]) -> int:
    """Preenche o cache CNEFE das tuplas ainda desconhecidas.

    Consulta so o que falta e para na primeira tabela que responde, porque as
    chaves sao aninhadas: numero exato implica logradouro existente.
    """
    novas = list({t for t in tuplas if t not in est.cache})
    if not novas:
        return 0
    for t in novas:
        est.cache[t] = Achado()

    for municipio, logr, num, loc, achou, confere in perguntar(est, novas, ChaveCnefe.NUMERO):
        achado = est.cache[como_tupla(municipio, logr, num, loc)]
        achado.numero = bool(achou)
        achado.localidade_confere = bool(confere)

    pendentes = [t for t in novas if not est.cache[t].numero]
    if not pendentes:
        return len(novas)

    for municipio, logr, num, loc, achou_logr in perguntar(est, pendentes, ChaveCnefe.LOGRADOURO):
        est.cache[como_tupla(municipio, logr, num, loc)].logradouro = bool(achou_logr)

    pendentes = [t for t in pendentes if not est.cache[t].logradouro]
    if not pendentes:
        return len(novas)

    for municipio, logr, num, loc, achou_loc in perguntar(est, pendentes, ChaveCnefe.LOCALIDADE):
        est.cache[como_tupla(municipio, logr, num, loc)].localidade = bool(achou_loc)
    return len(novas)


def etapa(t: Tupla, achado: Achado, cep_confere: bool) -> str:
    """Etapa da escada do geocodebr que essa linha alcancaria.

    Desempate do mais para o menos preciso: numero exato com localidade e cep
    (dn01) ate municipio apenas (dm01).
    """
    tem_numero = t[2] is not None
    if achado.numero:
        if achado.localidade_confere:
            return "dn01" if cep_confere else "dn03"
        return "dn02" if cep_confere else "dn04"
    if achado.logradouro:
        return "da04" if tem_numero else "dl04"
    if cep_confere:
        return "dc01" if achado.localidade else "dc02"
    return "db01" if achado.localidade else "dm01"


def etapas_de(est: Estado, pol: Politica, linhas: list[int] | None = None) -> dict[int, str]:
    linhas = list(range(len(est))) if linhas is None else linhas
    tuplas = [tupla(est, pol, i) for i in linhas]
    aquecer(est, tuplas)
    return {i: etapa(t, est.cache[t], est.cep_confere[i]) for i, t in zip(linhas, tuplas, strict=True)}


def score_fixo(etapas: Iterable[str]) -> float:
    """Score linear com o universo de categorias fixo em `ETAPAS`."""
    lista = list(etapas)
    contagem = collections.Counter(lista)
    k = len(ETAPAS)
    return 100 * sum((k - i) / k * contagem.get(cat, 0) / len(lista) for i, cat in enumerate(ETAPAS))


def ndcg_fixo(etapas: Iterable[str]) -> float:
    lista = list(etapas)
    contagem = collections.Counter(lista)
    dcg = sum(contagem.get(cat, 0) / len(lista) / math.log2(i + 2) for i, cat in enumerate(ETAPAS))
    idcg = sum(1 / math.log2(i + 2) for i in range(len(ETAPAS)))
    return 100 * dcg / idcg


def score_original(etapas: Iterable[str]) -> float:
    """Metrica de comparacao.py: o universo sao as categorias observadas."""
    lista = list(etapas)
    contagem = collections.Counter(lista)
    cats = [cat for cat in ETAPAS if contagem.get(cat)]
    k = len(cats)
    return 100 * sum((k - i) / k * contagem[cat] / len(lista) for i, cat in enumerate(cats))


def varredura(est: Estado, pol: Politica, etapas: dict[int, str]) -> list[tuple[str, Celula, float]]:
    """Avalia todas as celulas vizinhas (uma celula trocada) e ranqueia pelo delta.

    O delta e exato e pareado: soma, so nas linhas afetadas, a diferenca de peso
    entre a etapa antiga e a nova.
    """
    plano: list[tuple[str, Celula, list[int], list[Tupla]]] = []
    for tipo in TIPOS_SEGMENTO:
        linhas = est.linhas_por_tipo.get(tipo, [])
        if not linhas:
            continue
        for alternativa in ALTERNATIVAS.get(tipo, []):
            if alternativa == pol[tipo]:
                continue
            candidata = {**pol, tipo: alternativa}
            plano.append((tipo, alternativa, linhas, [tupla(est, candidata, i) for i in linhas]))
    if not plano:
        return []
    aquecer(est, [t for _, _, _, tuplas in plano for t in tuplas])

    ranking: list[tuple[str, Celula, float]] = []
    for tipo, alternativa, linhas, tuplas in plano:
        delta = 0.0
        for i, t in zip(linhas, tuplas, strict=True):
            nova = etapa(t, est.cache[t], est.cep_confere[i])
            if nova != etapas[i]:
                delta += PESO[nova] - PESO[etapas[i]]
        ranking.append((tipo, alternativa, 100 * delta / len(est)))
    return sorted(ranking, key=lambda r: r[2], reverse=True)


def otimizar(
    est: Estado, pol: Politica, max_varreduras: int, top: int
) -> tuple[Politica, dict[int, str], list[Alteracao], list[list[tuple[str, Celula, float]]]]:
    """Coordinate ascent: aceita a melhor celula vizinha enquanto ela melhorar a metrica."""
    etapas = etapas_de(est, pol)
    alteracoes: list[Alteracao] = []
    traco: list[list[tuple[str, Celula, float]]] = []
    for varredura_atual in range(1, max_varreduras + 1):
        ranking = varredura(est, pol, etapas)
        if not ranking:
            break
        traco.append(ranking)
        for tipo, celula, delta_pp in ranking[:top]:
            print(f"          {tipo:18s} {celula.papel:12s} {celula.quando:9s} {celula.alvo:12s} {delta_pp:+.4f} pp")
        tipo, celula, delta_pp = ranking[0]
        if delta_pp <= 0:
            break
        novas_etapas = etapas_de(est, {**pol, tipo: celula}, est.linhas_por_tipo.get(tipo, []))
        etapas.update(novas_etapas)
        pol = {**pol, tipo: celula}
        alteracoes.append(Alteracao(varredura_atual, tipo, celula, delta_pp))
        print(f"[varredura {varredura_atual}] {tipo} -> {celula}  delta pareado {delta_pp:+.3f} pp", flush=True)
    return pol, etapas, alteracoes, traco


def intervalo_pareado(iniciais: dict[int, str], finais: dict[int, str]) -> tuple[float, tuple[float, float]]:
    """Delta total e IC95% por bootstrap das linhas (as duas politicas veem as mesmas linhas)."""
    delta = np.array(
        [PESO[depois] - PESO[antes] for antes, depois in zip(iniciais.values(), finais.values(), strict=True)]
    )
    rng = np.random.default_rng(42)
    amostras = np.array([100 * delta[rng.integers(0, len(delta), len(delta))].mean() for _ in range(500)])
    inferior, superior = np.percentile(amostras, [2.5, 97.5]).tolist()
    media = delta.mean().item()
    return 100 * media, (inferior, superior)


def montar_relatorio(
    est: Estado,
    iniciais: dict[int, str],
    finais: dict[int, str],
    alteracoes: list[Alteracao],
    traco: list[list[tuple[str, Celula, float]]],
) -> Relatorio:
    delta, intervalo = intervalo_pareado(iniciais, finais)
    antes, depois = list(iniciais.values()), list(finais.values())
    return Relatorio(
        n=len(est),
        tuplas_no_cache=len(est.cache),
        delta_pareado_pp=delta,
        ic95=intervalo,
        score_fixo=(score_fixo(antes), score_fixo(depois)),
        ndcg_fixo=(ndcg_fixo(antes), ndcg_fixo(depois)),
        score_original=(score_original(antes), score_original(depois)),
        distribuicao_inicial=dict(collections.Counter(antes).most_common()),
        distribuicao_final=dict(collections.Counter(depois).most_common()),
        alteracoes=alteracoes,
        varreduras=traco,
    )


def imprimir_politica(pol: Politica, mudadas: set[str], titulo: str) -> None:
    print(f"\n{titulo}")
    for tipo in TIPOS_SEGMENTO:
        celula = pol[tipo]
        marca = "*" if tipo in mudadas else " "
        print(f"  {marca} {tipo:18s} {celula.papel:12s} {celula.quando:9s} {celula.alvo:12s} {celula.se_preenchido}")


def imprimir_relatorio(relatorio: Relatorio) -> None:
    inicial, final = relatorio.score_fixo
    ndcg_inicial, ndcg_final = relatorio.ndcg_fixo
    original_inicial, original_final = relatorio.score_original
    print(f"\nalteracoes aceitas: {len(relatorio.alteracoes)}, tuplas no cache: {relatorio.tuplas_no_cache}")
    print(f"n = {relatorio.n}, delta pareado: {relatorio.delta_pareado_pp:+.3f} pp  IC95% {relatorio.ic95}")
    print(f"score fixo  : {inicial:.2f} -> {final:.2f}   ndcg fixo: {ndcg_inicial:.2f} -> {ndcg_final:.2f}")
    print(f"score atual : {original_inicial:.2f} -> {original_final:.2f}   (universo observado, nao comparavel entre execucoes)")


def caminho_politica(nome: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", nome):
        raise SystemExit(f"nome de politica invalido: {nome!r}")
    pasta = PASTA_POLITICAS.resolve()
    caminho = (pasta / f"{nome}.json").resolve()
    if not caminho.is_relative_to(pasta):
        raise SystemExit(f"caminho fora de {pasta}: {nome!r}")
    return caminho


def ler_politica(nome: str) -> Politica:
    """Le uma politica gravada por `gravar_politica`."""
    dados = ler_json(caminho_politica(nome))
    brutos = dados.get("politica")
    if not isinstance(brutos, dict):
        raise SystemExit(f"politica sem o campo 'politica' em {nome!r}")
    politica: Politica = {}
    for tipo in TIPOS_SEGMENTO:
        celula = brutos.get(tipo)
        if not isinstance(celula, dict):
            raise SystemExit(f"politica {nome!r} sem celula para {tipo!r}")
        politica[tipo] = Celula.de_dict({chave: str(valor) for chave, valor in celula.items()})
    return politica


def gravar_politica(nome: str, pol: Politica, relatorio: Relatorio, args: argparse.Namespace) -> Path:
    """Grava politica e relatorio, acumulando execucoes no mesmo nome em `historico`."""
    PASTA_POLITICAS.mkdir(parents=True, exist_ok=True)
    caminho = caminho_politica(nome)
    anterior = ler_json(caminho) if caminho.is_file() else {}
    historico = anterior.get("historico")
    execucoes = list(historico) if isinstance(historico, list) else []
    caminho.write_text(
        json.dumps(
            {
                "politica": {
                    tipo: {"papel": c.papel, "quando": c.quando, "alvo": c.alvo, "se_preenchido": c.se_preenchido}
                    for tipo, c in pol.items()
                },
                "amostra": {"base": str(args.base), "n": args.n, "sal": args.sal},
                "modelo": str(args.tagger),
                "ontologia": list(TIPOS_SEGMENTO),
                "historico": [*execucoes, asdict(relatorio)],
            },
            indent=2,
            ensure_ascii=False,
            default=str,
        )
    )
    return caminho


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base", type=Path, default=BASE_PADRAO)
    parser.add_argument("--n", type=int, default=60000)
    parser.add_argument("--tagger", type=Path, default=DIR_DADOS / "modelos" / "tagger_v2.crf")
    parser.add_argument("--max-varreduras", type=int, default=8)
    parser.add_argument("--sal", default="0", help="muda a amostra mantendo o tamanho (holdout)")
    parser.add_argument("--top", type=int, default=3, help="candidatos mostrados por varredura")
    parser.add_argument("--nome", default="", help="nome do json em data/politicas (padrao derivado do modo)")
    parser.add_argument("--politica", default="", help="avalia uma politica salva, sem otimizar")
    args = parser.parse_args()

    t0 = time.perf_counter()
    est = criar_estado(args)
    contagem = collections.Counter(t for s in est.segs for t, _ in s)
    t0 = cronometrar(
        f"amostra + segmentacao: {len(est)} linhas, "
        + ", ".join(f"{k}={v / len(est):.1%}" for k, v in contagem.most_common(6)),
        t0,
    )

    iniciais = etapas_de(est, INICIO)
    if args.politica:
        pol = ler_politica(args.politica)
        finais = etapas_de(est, pol)
        alteracoes: list[Alteracao] = []
        traco: list[list[tuple[str, Celula, float]]] = []
        nome = args.nome or f"avaliacao_{args.politica}"
        imprimir_politica(pol, set(), f"politica avaliada: {args.politica} (amostra sal={args.sal})")
    else:
        _ = cronometrar(f"baseline: {len(est.cache)} tuplas no cache", t0)
        imprimir_politica(INICIO, set(), f"politica inicial (score fixo {score_fixo(iniciais.values()):.2f})")
        pol, finais, alteracoes, traco = otimizar(est, INICIO, args.max_varreduras, args.top)
        nome = args.nome or "otimizada"
        imprimir_politica(pol, {a.tipo for a in alteracoes}, "politica otimizada")

    relatorio = montar_relatorio(est, iniciais, finais, alteracoes, traco)
    imprimir_relatorio(relatorio)
    print(f"\npolitica e relatorio gravados em: {gravar_politica(nome, pol, relatorio, args)}")
    _ = cronometrar("fim", t0)


if __name__ == "__main__":
    main()
