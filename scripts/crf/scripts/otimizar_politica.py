"""Politica pos-CRF: em que campo do `Endereco` cada tipo de segmento cai.

Contexto
--------
`segmento_como_endereco` (src/separador_endereco.rs) decide o destino de cada
tipo da ontologia (`anotacao/ontologia.py`). Aqui a decisao vira dado — uma
*decision list* por tipo e otimizada por coordinate ascent contra o score de
`geocode/comparacao.py`, o mesmo de `crf geocode comparar`. O universo de
categorias e fixo nas 25 etapas do geocodebr mais "(nao encontrado)": so assim
duas politicas ficam comparaveis (com o universo observado, o score muda
porque uma categoria desapareceu).

    Regra(termos, campo, se_preenchido)

A lista e avaliada da primeira para a ultima: a primeira regra cujos termos
valem manda o valor para `campo`; sem regra que case, o segmento e descartado.
Regra sem termos vale sempre, entao `Regra((), Campo.LOGRADOURO)` e "sempre
logradouro" e a lista vazia e "descarta sempre".

Os termos sao conjuncoes (`&`) de atomos, cada um opcionalmente negado (`!`).
O vocabulario olha a vizinhanca e a composicao da linha, nunca o corpus:

    primeiro, ultimo
    antes.tipo=<tipo>, antes.campo=<campo>
    depois.tipo=<tipo>, depois.campo=<campo>
    antes_de=<tipo>, depois_de=<tipo>       # nao adjacente
    tem=<tipo>
    dono_unico=<campo>                     # nenhum outro tipo disputa o campo

Duas invariantes sustentam a busca. **Linha-local**: um atomo le so os
segmentos da propria linha e a politica — assim trocar a regra de um tipo muda
apenas as linhas que contem esse tipo, e o delta da varredura continua exato.
**Intencao, nao escrita**: vizinho e lido pelo destino primario da regra dele
(o do primeiro ramo que nao descarta), nao pelo que ele escreveu; sem isso
`aplicar` precisaria de ponto fixo e a ordem dos segmentos importaria.

Por que condicoes e nao so campo: medido em 5k linhas com a politica anterior,
`anterior=localidade` vinha 43% das vezes de `complemento` e
`anterior=logradouro` 20% de `parcela`/`nucleo_rural`/`recurso_natural` — um
`Campo` como contexto mistura tipos com papeis diferentes. Dai `antes.tipo`.
Do mesmo modo `dono_unico` e atomo, com o campo explicito: compoe com `&` e com
`!`, e permite o par "logradouro se sou o unico dono, senao localidade".

Quem decide o `tipo_resultado` de cada endereco e o proprio geocodebr, entao
nada da escada de matching (chaves, Jaro, desempate) e reimplementado aqui.
`campo=complemento` nao existe no geocodebr: complemento equivale a ignorar.

Juntar dois segmentos no mesmo campo nunca ganhou: a chave do geocodebr e
comparacao exata de string, entao anexar o valor de outro tipo a um logradouro
correto destroi o match (medido: `logradouro` com `juntar` empata com `manter`,
+0.000 pp, e 9.3% das linhas ficavam com logradouro sujo por parcela anexada).
O desempate virou `manter` (primeiro ganha) e `substituir` (o tipo posterior
sobrescreve), que e como a politica escolhe o vencedor quando dois tipos
disputam o mesmo campo.

Custo
-----
O resultado do geocodebr depende so da tupla de campos de cada linha —
(estado, municipio, logradouro, numero, localidade, cep) — entao o cache por
tupla faz cada varredura consultar apenas as tuplas que ainda nao existem, e
apenas das linhas do tipo cuja celula mudou.

Uso
---
    uv run python scripts/otimizar_politica.py --n 5000
    uv run python scripts/otimizar_politica.py --inicio otimizada --sal 1 --varreduras 0
    make otimizar N=5000

`--varreduras 0` so avalia a politica de partida. O json em
`data/politicas/<nome>.json` guarda a politica (a decision list de cada tipo, com
os termos aninhados), a amostra e o score: e o ponto de partida da proxima
otimizacao (`--inicio <nome>`).
`--reinicios K` sortea K chutes apos a otimizacao: perturba uma ou duas celulas,
ponderadas pelas linhas de cada tipo, e repete o coordinate ascent — e o teste de
otimo local.

A vizinhanca tem edicoes estruturais (remover ou trocar de lugar uma regra,
trocar campo ou desempate, negar/trocar/remover/acrescentar um termo) e a
criacao de regra nova com condicao de um unico termo. Duas podas mantem o custo
disso: o termo precisa disparar em pelo menos 5 linhas (`MIN_LINHAS`) e em no
maximo 95% das ocorrencias do tipo na amostra, e a candidata precisa mudar a
tupla de ao menos 5 linhas — o que nao muda tupla nao muda score e nao chega ao
geocodebr.

`--minimo 0.2` nao e conservadorismo: a execucao de 1200 linhas aceitou
`empreendimento -> localidade:sozinho` por +0.0201 pp, ganho que nao reproduziu
em 5000 linhas (delta 0.0, nenhuma troca aceita). Abaixo de ~0.2 pp o delta e
ruido de amostra, nao sinal.

`--n` e o custo: cada chamada do geocodebr paga ~20s de varredura do CNEFE mais
~20ms por tupla nova, e uma varredura gera dezenas de milhares de tuplas. Por
isso as tuplas ficam em `--cache`, um parquet chaveado pela tupla
de campos: a segunda execucao, cada reinicio e cada holdout so pagam o inedito,
e o cache vale para qualquer tagger ou politica porque o CNEFE nao muda. Use
`--sal 1` para conferir a politica num holdout e `--minimo 0.2` para nao aceitar
ganho que e ruido de amostra.
"""

from __future__ import annotations

import collections
import json
import random
import re
import sqlite3
import sys
import time
import warnings
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field, replace
from enum import StrEnum
from pathlib import Path
from typing import Annotated, cast

import duckdb
import enderecobr
import geocodebr
import pandas as pd
import polars as pl
import pyarrow as pa
import typer
from geocodebr import definir_campos
from geocodebr.constants import DATA_RELEASE
from tqdm import tqdm

from crf_endereco.anotacao.ontologia import TIPOS_SEGMENTO
from crf_endereco.config import CAMINHO_DATASET, DIR_DADOS
from crf_endereco.features import ExtratorFeature
from crf_endereco.geocode.comparacao import (
    ORDEM_TIPO_RESULTADO,
    SEM_RESULTADO,
    calcular_ndcg,
    calcular_score_linear,
    eh_sqlite,
)
from crf_endereco.modelo import crf as modelo_crf

BASE_PADRAO = CAMINHO_DATASET
PASTA_MODELOS = DIR_DADOS / "modelos"
PASTA_POLITICAS = DIR_DADOS / "politicas"
# Cache das tuplas ja geocodificadas: a chave e a tupla de campos, entao o
# arquivo vale para qualquer tagger e politica — mas nao para outra release do
# CNEFE, que muda as respostas.
CACHE_PADRAO = DIR_DADOS / f"cache_geocodebr_{DATA_RELEASE}.parquet"

# Universo fixo do score: as 25 etapas do geocodebr e o "nao encontrado".
ORDEM = (*ORDEM_TIPO_RESULTADO, SEM_RESULTADO)
# Peso linear decrescente por posicao, igual ao `calcular_score_linear` de
# comparacao.py com o universo fixo. Ser linear e o que torna o delta de uma
# varredura exato sem recalcular o score inteiro.
PESO = {categoria: (len(ORDEM) - i) / len(ORDEM) for i, categoria in enumerate(ORDEM)}

# Tuplas por chamada do geocodebr: cada chamada paga ~4s de varredura do CNEFE,
# e lotes grandes demais estouram a memoria do DuckDB.
LOTE_GEOCODE = 4000
# Piso de suporte de uma candidata: condicao que muda menos linhas que isto, ou
# regra que so altera menos linhas que isto, e ruido de amostra — nao paga
# geocodebr nem entra na decisao.
MIN_LINHAS = 5
# Tetos da decision list: mais ramos que isso viram overfit de 5000 linhas e
# encarecem o port para o Rust, que reimplementa esta mesma semantica.
MAX_REGRAS = 3
MAX_TERMOS = 3
# Teto do buffer manager do DuckDB. Sem ele o geocodebr ocupa ~80% da RAM da
# maquina e o processo morre por OOM com ~7 GB.
MEMORIA_GEOCODEBR = "3GB"

CAMPOS_GEOCODEBR = definir_campos(
    estado="estado",
    municipio="municipio",
    logradouro="logradouro",
    numero="numero",
    cep="cep",
    localidade="localidade",
)

Tupla = tuple[str | None, str | None, str | None, str | None, str | None, str | None]
TUDO_NULO: Tupla = (None, None, None, None, None, None)


class Campo(StrEnum):
    """Campo do `Endereco` que recebe o valor do segmento."""

    LOGRADOURO = "logradouro"
    NUMERO = "numero"
    LOCALIDADE = "localidade"
    CEP = "cep"
    IGNORAR = "ignorar"


class SePreenchido(StrEnum):
    """O que fazer quando o campo de destino ja tem valor."""

    MANTER = "manter"
    SUBSTITUIR = "substituir"


class Atomo(StrEnum):
    """Predicado sobre o contexto de uma ocorrencia, dentro da propria linha.

    Nenhum atomo olha estatistica do corpus: e o que garante que trocar a regra
    de um tipo so muda as linhas que contem esse tipo, logo o delta da varredura
    continua exato. Vizinho e lido pela intencao — o destino primario da regra
    do vizinho —, nunca pelo que ele escreveu, entao `aplicar` e uma passada
    unica, sem ponto fixo e sem depender da ordem das regras entre tipos.
    """

    PRIMEIRO = "primeiro"
    ULTIMO = "ultimo"
    ANTES_TIPO = "antes.tipo"
    ANTES_CAMPO = "antes.campo"
    DEPOIS_TIPO = "depois.tipo"
    DEPOIS_CAMPO = "depois.campo"
    ANTES_DE = "antes_de"
    DEPOIS_DE = "depois_de"
    TEM = "tem"
    DONO_UNICO = "dono_unico"


# Atomos que nao levam valor: a posicao ja e o valor.
SEM_VALOR = frozenset({Atomo.PRIMEIRO, Atomo.ULTIMO})
CAMPOS_VIZINHO = tuple(str(campo) for campo in Campo)
CAMPOS_DONO = tuple(str(campo) for campo in Campo if campo is not Campo.IGNORAR)


@dataclass(frozen=True)
class Termo:
    """Um atomo, opcionalmente negado: a unidade de um termo de condicao."""

    atomo: Atomo
    valor: str | None = None
    negado: bool = False

    def para_texto(self) -> str:
        prefixo = "!" if self.negado else ""
        if self.atomo in SEM_VALOR:
            return f"{prefixo}{self.atomo}"
        return f"{prefixo}{self.atomo}={self.valor}"


@dataclass(frozen=True)
class Regra:
    """Um ramo da decision list: se todos os termos valem, o valor vai para `campo`.

    `termos` vazio vale sempre. `campo=ignorar` descarta o segmento e, por ser
    uma regra como outra qualquer, permite "descarta quando X, senao logradouro".
    """

    termos: tuple[Termo, ...] = ()
    campo: Campo = Campo.IGNORAR
    se_preenchido: SePreenchido = SePreenchido.MANTER

    def para_texto(self) -> str:
        condicao = " & ".join(termo.para_texto() for termo in self.termos) or "sempre"
        if self.campo is Campo.IGNORAR:
            return f"{condicao} => ignorar"
        return f"{condicao} => {self.campo}/{self.se_preenchido}"


Regras = tuple[Regra, ...]
Politica = dict[str, Regras]


def valores_de(atomo: Atomo) -> tuple[str, ...]:
    """Valores que fazem sentido para o atomo — o dominio da busca."""
    if atomo in SEM_VALOR:
        return ()
    if atomo is Atomo.DONO_UNICO:
        return CAMPOS_DONO
    if atomo in (Atomo.ANTES_CAMPO, Atomo.DEPOIS_CAMPO):
        return CAMPOS_VIZINHO
    return tuple(TIPOS_SEGMENTO)


def termos_possiveis() -> list[Termo]:
    """Dominio de termos, na ordem canonica — a mesma em toda execucao."""
    return [
        Termo(atomo, valor, negado)
        for atomo in Atomo
        for valor in (valores_de(atomo) or (None,))
        for negado in (False, True)
    ]


def regras_para_texto(regras: Regras) -> str:
    """Forma legivel da lista, so para imprimir e para o json: nao e reparseada."""
    return "; ".join(regra.para_texto() for regra in regras) or str(Campo.IGNORAR)


@dataclass(frozen=True)
class Contexto:
    """O que os atomos veem numa linha, dada uma politica."""

    tipos: tuple[str, ...]
    destinos: tuple[Campo, ...]
    donos: dict[Campo, frozenset[str]]


def campo_primario(regras: Regras) -> Campo:
    """Destino que o tipo persegue: o do primeiro ramo que nao descarta.

        E a leitura de `antes`/`depois`. Contar o que o vizinho escreveu de fato
    dependeria da ordem de avaliacao e faria `aplicar` divergir conforme a posicao
    na linha; a intencao e estavel e dispensa ponto fixo.
    """
    return next(
        (regra.campo for regra in regras if regra.campo is not Campo.IGNORAR),
        Campo.IGNORAR,
    )


def preparar(pol: Politica, segs: Sequence[tuple[str, str]]) -> Contexto:
    donos: dict[Campo, set[str]] = collections.defaultdict(set)
    for tipo in dict.fromkeys(tipo for tipo, _ in segs):
        for regra in pol[tipo]:
            if regra.campo is not Campo.IGNORAR:
                donos[regra.campo].add(tipo)
    return Contexto(
        tipos=tuple(tipo for tipo, _ in segs),
        destinos=tuple(campo_primario(pol[tipo]) for tipo, _ in segs),
        donos={campo: frozenset(tipos) for campo, tipos in donos.items()},
    )


def satisfaz(termo: Termo, posicao: int, ctx: Contexto) -> bool:
    """Se o termo vale na ocorrencia `posicao` da linha descrita por `ctx`."""
    atomo = termo.atomo
    if atomo is Atomo.PRIMEIRO:
        vale = posicao == 0
    elif atomo is Atomo.ULTIMO:
        vale = posicao == len(ctx.tipos) - 1
    elif atomo is Atomo.ANTES_TIPO:
        vale = posicao > 0 and ctx.tipos[posicao - 1] == termo.valor
    elif atomo is Atomo.ANTES_CAMPO:
        vale = posicao > 0 and str(ctx.destinos[posicao - 1]) == termo.valor
    elif atomo is Atomo.DEPOIS_TIPO:
        vale = posicao + 1 < len(ctx.tipos) and ctx.tipos[posicao + 1] == termo.valor
    elif atomo is Atomo.DEPOIS_CAMPO:
        vale = (
            posicao + 1 < len(ctx.tipos)
            and str(ctx.destinos[posicao + 1]) == termo.valor
        )
    elif atomo is Atomo.ANTES_DE:
        vale = termo.valor in ctx.tipos[:posicao]
    elif atomo is Atomo.DEPOIS_DE:
        vale = termo.valor in ctx.tipos[posicao + 1 :]
    elif atomo is Atomo.TEM:
        vale = termo.valor in ctx.tipos
    else:  # DONO_UNICO
        vale = ctx.donos.get(Campo(str(termo.valor)), frozenset()) == frozenset(
            {ctx.tipos[posicao]}
        )
    return vale != termo.negado


def casar(regras: Regras, posicao: int, ctx: Contexto) -> Regra | None:
    """Primeira regra cujos termos valem; `None` quando nenhuma casa (descarta)."""
    for regra in regras:
        if all(satisfaz(termo, posicao, ctx) for termo in regra.termos):
            return regra
    return None


def aplicar(pol: Politica, segs: Sequence[tuple[str, str]]) -> dict[Campo, str]:
    """Monta os campos do endereco a partir dos segmentos, segundo a politica."""
    ctx = preparar(pol, segs)
    campos: dict[Campo, str] = {}
    for posicao, (tipo, valor) in enumerate(segs):
        regra = casar(pol[tipo], posicao, ctx)
        if regra is None or regra.campo is Campo.IGNORAR:
            continue
        if regra.se_preenchido is SePreenchido.SUBSTITUIR or regra.campo not in campos:
            campos[regra.campo] = valor
    return campos


def trocar_regra(regras: Regras, indice: int, regra: Regra) -> Regras:
    return regras[:indice] + (regra,) + regras[indice + 1 :]


def vizinhas(regras: Regras) -> list[Regras]:
    """Edicoes estruturais: uma regra, um termo ou a ordem, por vez.

    Regra nova com condicao fica em `candidatas`: o dominio de termos e grande e
    ali a poda por suporte e por linhas afetadas filtra antes de pagar o
    geocodebr. Aqui tudo e barato e finito, entao entra inteiro.
    """
    saida: list[Regras] = []
    for indice, regra in enumerate(regras):
        if len(regras) > 1:
            saida.append(regras[:indice] + regras[indice + 1 :])
        if indice + 1 < len(regras):
            saida.append(
                regras[:indice] + (regras[indice + 1], regra) + regras[indice + 2 :]
            )
        for campo in Campo:
            if campo is not regra.campo:
                saida.append(trocar_regra(regras, indice, replace(regra, campo=campo)))
        for se_preenchido in SePreenchido:
            if se_preenchido is not regra.se_preenchido:
                saida.append(
                    trocar_regra(
                        regras, indice, replace(regra, se_preenchido=se_preenchido)
                    )
                )
        for posicao, termo in enumerate(regra.termos):
            negado = replace(termo, negado=not termo.negado)
            saida.append(
                trocar_regra(regras, indice, with_termo(regra, posicao, negado))
            )
            for valor in valores_de(termo.atomo):
                if valor != termo.valor:
                    outro = replace(termo, valor=valor)
                    saida.append(
                        trocar_regra(regras, indice, with_termo(regra, posicao, outro))
                    )
            if len(regra.termos) > 1:
                sem = replace(
                    regra, termos=regra.termos[:posicao] + regra.termos[posicao + 1 :]
                )
                saida.append(trocar_regra(regras, indice, sem))
    return saida


def with_termo(regra: Regra, posicao: int, termo: Termo) -> Regra:
    return replace(
        regra, termos=regra.termos[:posicao] + (termo,) + regra.termos[posicao + 1 :]
    )


def perturbar(pol: Politica, rng: random.Random, massa: dict[str, int]) -> Politica:
    """Chute para escapar de otimo local: sorteia uma ou duas listas novas.

    O sorteio e ponderado pelas linhas de cada tipo: metade da ontologia aparece
    em menos de 50 linhas da amostra, e chutar num tipo sem massa devolve o
    reinicio ao mesmo ponto.
    """
    tipos = [tipo for tipo in TIPOS_SEGMENTO if massa.get(tipo)]
    sorteio = rng.choices(
        tipos, weights=[massa[tipo] for tipo in tipos], k=rng.choice((1, 2))
    )
    repos = dict(pol)
    for tipo in dict.fromkeys(sorteio):
        campo = rng.choice(list(Campo))
        if campo is Campo.IGNORAR:
            repos[tipo] = ()
            continue
        termo = rng.choice(termos_possiveis())
        repos[tipo] = (Regra((termo,), campo, rng.choice(list(SePreenchido))),)
    return repos


_CEPS: dict[str, str | None] = {}


def cep_limpo(valor: str | None) -> str | None:
    """Normaliza o cep: o geocodebr recusa caracteres invalidos no campo cep.

    O cep da base vem do json de `meta` e o do segmento vem do CRF, e nenhum dos
    dois passa por validacao antes. Cep zerado vira None (nao existe no CNEFE).
    """
    if valor is None:
        return None
    if valor not in _CEPS:
        padrao = enderecobr.padronizar_cep_leniente(valor)
        _CEPS[valor] = None if set(padrao) <= {"0", "-"} else padrao
    return _CEPS[valor]


# Ponto de partida: a tabela de uma celula por tipo que a otimizacao anterior
# convergiu, escrita agora como decision list de um ramo.
INICIAL: Politica = {
    "logradouro": (Regra((), Campo.LOGRADOURO),),
    "numero": (Regra((), Campo.NUMERO),),
    "complemento": (),
    "parcela": (Regra((), Campo.LOGRADOURO),),
    "empreendimento": (Regra((), Campo.LOCALIDADE),),
    "localidade": (Regra((), Campo.LOCALIDADE),),
    "nucleo_rural": (Regra((), Campo.LOCALIDADE),),
    "recurso_natural": (),
    "referencia": (),
    "ponto_referencia": (),
    "denominacao": (),
    "quilometragem_via": (Regra((), Campo.NUMERO),),
    "cep": (Regra((), Campo.CEP),),
    "municipio": (),
    "uf": (),
    "cadastro": (),
    "ruido": (),
    "outros": (),
}


@dataclass
class Avaliacao:
    """Amostra segmentada, tuplas da politica corrente e cache do geocodebr."""

    estado: list[str]
    municipio: list[str]
    cep: list[str | None]
    segs: list[list[tuple[str, str]]]
    linhas_por_tipo: dict[str, list[int]]
    cache: dict[Tupla, str] = field(default_factory=dict)
    tuplas: list[Tupla] = field(default_factory=list)
    etapas: list[str] = field(default_factory=list)
    caminho_cache: Path | None = None

    def __len__(self) -> int:
        return len(self.segs)

    def chave(self, i: int, campos: dict[Campo, str]) -> Tupla:
        """Tupla de busca no CNEFE. O cep do segmento, quando houver, vence o da base."""
        return (
            self.estado[i],
            self.municipio[i],
            campos.get(Campo.LOGRADOURO),
            campos.get(Campo.NUMERO),
            campos.get(Campo.LOCALIDADE),
            cep_limpo(campos.get(Campo.CEP)) or self.cep[i],
        )

    def definir(self, pol: Politica, linhas: Iterable[int]) -> None:
        """Recalcula as tuplas das linhas afetadas por uma troca de celula."""
        for i in linhas:
            self.tuplas[i] = self.chave(i, aplicar(pol, self.segs[i]))

    def fixar_etapas(self) -> None:
        self.etapas = [self.cache[tupla] for tupla in self.tuplas]


def limitar_duckdb(limite: str = MEMORIA_GEOCODEBR) -> None:
    """Poe teto de memoria nas conexoes que o geocodebr abre.

    `geocodebr.geocode` cria a conexao DuckDB por dentro (`create_geocodebr_db`)
    e nao expoe `memory_limit`; sem o teto o buffer manager ocupa ~80% da RAM e
    o processo morre por OOM nesta maquina. `create_geocodebr_db` nao e API
    publica do pacote, por isso o acesso por `vars()`.
    """
    modulo = sys.modules["geocodebr.geocode"]
    criar = cast(
        Callable[..., duckdb.DuckDBPyConnection], vars(modulo)["create_geocodebr_db"]
    )

    def criar_com_limite(*args: object, **kwargs: object) -> duckdb.DuckDBPyConnection:
        conexao = criar(*args, **kwargs)
        _ = conexao.execute(f"SET memory_limit = '{limite}'")
        _ = conexao.execute("SET preserve_insertion_order = false")
        return conexao

    vars(modulo)["create_geocodebr_db"] = criar_com_limite


COLUNAS_TUPLA = ("estado", "municipio", "logradouro", "numero", "localidade", "cep")


def ler_cache(caminho: Path) -> dict[Tupla, str]:
    """Tuplas ja geocodificadas por execucoes anteriores.

    A chave e a tupla de campos, e nao a politica nem o tagger: o que muda entre
    execucoes e como os campos sao montados, nao o CNEFE.
    """
    if not caminho.is_file():
        return {}
    tabela = pl.read_parquet(caminho)
    return {
        (linha[0], linha[1], linha[2], linha[3], linha[4], linha[5]): linha[6]
        for linha in tabela.select([*COLUNAS_TUPLA, "tipo_resultado"]).iter_rows()
    }


def gravar_cache(caminho: Path, cache: dict[Tupla, str]) -> None:
    """Reescreve o cache inteiro depois de cada lote do geocodebr.

    Dezenas de milhares de linhas custam menos de um segundo, e assim uma
    execucao interrompida nao perde o que ja foi pago ao geocodebr.
    """
    _ = caminho.parent.mkdir(parents=True, exist_ok=True)
    tuplas = list(cache)
    tabela = pl.DataFrame(
        {
            nome: pl.Series([tupla[i] for tupla in tuplas], dtype=pl.Utf8)
            for i, nome in enumerate(COLUNAS_TUPLA)
        }
        | {"tipo_resultado": pl.Series(list(cache.values()), dtype=pl.Utf8)}
    )
    tabela.write_parquet(caminho)


def geocodificar(
    cache: dict[Tupla, str], tuplas: Iterable[Tupla], caminho: Path | None = None
) -> int:
    """Preenche no cache o `tipo_resultado` das tuplas ainda desconhecidas."""
    novas = [tupla for tupla in dict.fromkeys(tuplas) if tupla not in cache]
    for inicio in range(0, len(novas), LOTE_GEOCODE):
        lote = novas[inicio : inicio + LOTE_GEOCODE]
        entrada = pl.DataFrame(
            {
                "idx": pl.Series(range(len(lote)), dtype=pl.UInt32),
                "estado": pl.Series([t[0] for t in lote], dtype=pl.Utf8),
                "municipio": pl.Series([t[1] for t in lote], dtype=pl.Utf8),
                "logradouro": pl.Series([t[2] for t in lote], dtype=pl.Utf8),
                "numero": pl.Series([t[3] for t in lote], dtype=pl.Utf8),
                "localidade": pl.Series([t[4] for t in lote], dtype=pl.Utf8),
                "cep": pl.Series([t[5] for t in lote], dtype=pl.Utf8),
            }
        )
        with warnings.catch_warnings():
            # o geocodebr avisa, a cada chamada, que numero nao numerico virou NA
            warnings.simplefilter("ignore", UserWarning)
            saida = cast(
                pa.Table,
                geocodebr.geocode(
                    entrada, campos_endereco=CAMPOS_GEOCODEBR, verboso=False
                ),
            )
        for linha in saida.select(["idx", "tipo_resultado"]).to_pylist():
            categoria = linha["tipo_resultado"] or SEM_RESULTADO
            if categoria not in PESO:
                raise SystemExit(
                    f"tipo_resultado inesperado do geocodebr: {categoria!r}"
                )
            cache[lote[linha["idx"]]] = categoria
        if caminho is not None:
            gravar_cache(caminho, cache)
        print(
            f"[geocodebr] {min(inicio + LOTE_GEOCODE, len(novas))}/{len(novas)}",
            flush=True,
        )
    return len(novas)


def pontuar(etapas: Sequence[str]) -> tuple[float, float, dict[str, int]]:
    """Score linear e NDCG da amostra, com o universo fixo de categorias."""
    contagem = collections.Counter(etapas)
    tabela = pd.DataFrame(
        {
            "categoria": list(ORDEM),
            "prop_estruturado": [
                100 * contagem.get(categoria, 0) / len(etapas) for categoria in ORDEM
            ],
        }
    )
    return (
        100 * calcular_score_linear(tabela),
        100 * calcular_ndcg(tabela),
        {categoria: contagem.get(categoria, 0) for categoria in ORDEM},
    )


def termos_uteis(
    av: Avaliacao, pol: Politica, tipo: str, linhas: Sequence[int]
) -> list[Termo]:
    """Termos que podem mudar alguma coisa neste tipo.

    Poda por suporte: uma conjuncao nunca dispara mais que cada termo seu, entao
    termo abaixo do piso nao gera candidata com efeito, e o corte de cima evita
    gastar geocodebr no que e praticamente incondicional — caso que a varredura
    estrutural ja cobre trocando o campo de uma regra sem termos.
    """
    ctxs = [preparar(pol, av.segs[i]) for i in linhas]
    posicoes = [
        (ctx, j) for ctx in ctxs for j, rotulo in enumerate(ctx.tipos) if rotulo == tipo
    ]
    teto = 0.95 * len(posicoes)
    uteis: list[Termo] = []
    for termo in termos_possiveis():
        suporte = sum(1 for ctx, j in posicoes if satisfaz(termo, j, ctx))
        if MIN_LINHAS <= suporte <= teto:
            uteis.append(termo)
    return uteis


def candidatas(
    av: Avaliacao, pol: Politica, tipo: str, linhas: Sequence[int]
) -> list[Regras]:
    """Vizinhanca completa do tipo: edicoes estruturais mais condicao nova.

    Condicao nova entra no fim da lista (prioridade minima) e sempre com
    `manter`; o resto — subir a regra, trocar o desempate — e edicao estrutural,
    entao nenhuma combinacao fica inalcancavel.
    """
    atuais = pol[tipo]
    saida = [vizinha for vizinha in vizinhas(atuais) if vizinha != atuais]
    uteis = termos_uteis(av, pol, tipo, linhas)
    if len(atuais) < MAX_REGRAS:
        for termo in uteis:
            saida.extend(atuais + (Regra((termo,), campo),) for campo in Campo)
    for indice, regra in enumerate(atuais):
        if len(regra.termos) < MAX_TERMOS:
            presentes = set(regra.termos)
            for termo in uteis:
                if termo not in presentes:
                    saida.append(
                        trocar_regra(
                            atuais,
                            indice,
                            replace(regra, termos=regra.termos + (termo,)),
                        )
                    )
    return list(dict.fromkeys(saida))


def varredura(av: Avaliacao, pol: Politica) -> list[tuple[str, Regras, float]]:
    """Delta no score de cada vizinha, medido so nas linhas do tipo.

    O delta e exato e pareado: o score e linear no peso de cada linha, entao a
    soma da diferenca de peso nas linhas afetadas e a variacao do score total.

    Antes de chamar o geocodebr, a candidata e filtrada pelas linhas em que ela
    muda a tupla: o que nao muda tupla nao muda score, e a tupla nova e o unico
    custo real (cada uma e uma consulta ao CNEFE, ~20ms).
    """
    plano: list[tuple[str, Regras, list[int], list[Tupla]]] = []
    descartadas = 0
    for tipo in TIPOS_SEGMENTO:
        linhas = av.linhas_por_tipo.get(tipo, [])
        if not linhas:
            continue
        for candidata in candidatas(av, pol, tipo, linhas):
            politica = {**pol, tipo: candidata}
            novas = [av.chave(i, aplicar(politica, av.segs[i])) for i in linhas]
            afetadas = [
                (i, tupla)
                for i, tupla in zip(linhas, novas, strict=True)
                if tupla != av.tuplas[i]
            ]
            if len(afetadas) < MIN_LINHAS:
                descartadas += 1
                continue
            plano.append(
                (
                    tipo,
                    candidata,
                    [i for i, _ in afetadas],
                    [tupla for _, tupla in afetadas],
                )
            )
    if not plano:
        print(
            f"[varredura] nenhuma candidata com efeito ({descartadas} descartadas)",
            flush=True,
        )
        return []
    novas = geocodificar(
        av.cache,
        [tupla for _, _, _, tuplas in plano for tupla in tuplas],
        av.caminho_cache,
    )
    total = len(plano) + descartadas
    print(
        f"[varredura] {len(plano)}/{total} candidatas com efeito, {novas} tuplas novas",
        flush=True,
    )
    ranking = [
        (
            tipo,
            candidata,
            100
            * sum(
                PESO[av.cache[tupla]] - PESO[av.etapas[i]]
                for i, tupla in zip(linhas, tuplas, strict=True)
            )
            / len(av),
        )
        for tipo, candidata, linhas, tuplas in plano
    ]
    return sorted(ranking, key=lambda candidata: candidata[2], reverse=True)


def otimizar(
    av: Avaliacao, pol: Politica, max_varreduras: int, top: int, minimo: float
) -> tuple[Politica, list[tuple[int, str, Regras, float]]]:
    """Coordinate ascent: aceita a melhor vizinha enquanto ela melhorar `minimo`."""
    alteracoes: list[tuple[int, str, Regras, float]] = []
    for numero in range(1, max_varreduras + 1):
        ranking = varredura(av, pol)
        for tipo, regras, delta in ranking[:top]:
            print(
                f"          {tipo:18s} {regras_para_texto(regras):48s} {delta:+.4f} pp"
            )
        if not ranking or ranking[0][2] <= minimo:
            break
        tipo, regras, delta = ranking[0]
        pol = {**pol, tipo: regras}
        linhas = av.linhas_por_tipo.get(tipo, [])
        av.definir(pol, linhas)
        for i in linhas:
            av.etapas[i] = av.cache[av.tuplas[i]]
        alteracoes.append((numero, tipo, regras, delta))
        print(
            f"[varredura {numero}] {tipo} -> {regras_para_texto(regras)}  {delta:+.3f} pp",
            flush=True,
        )
    return pol, alteracoes


def ler_base(caminho: Path) -> pl.DataFrame:
    """Le (estado, municipio, cep, endereco) do dataset anotado ou de um parquet."""
    if eh_sqlite(caminho):
        return pl.DataFrame(
            _ler_enderecos_sqlite(caminho),
            schema={"estado": pl.Utf8, "municipio": pl.Utf8, "cep": pl.Utf8, "endereco": pl.Utf8},
            orient="row",
        )
    tabela = pl.read_parquet(caminho)
    return tabela.select(
        estado=pl.col("uf"),
        municipio=pl.col("municipio"),
        cep=pl.col("cep") if "cep" in tabela.columns else pl.lit(None, pl.Utf8),
        endereco=pl.col("DscEndereco"),
    ).filter(
        pl.col("endereco").is_not_null() & (pl.col("endereco").str.strip_chars() != "")
    )


def _ler_enderecos_sqlite(
    caminho: Path,
) -> list[tuple[str, str | None, str | None, str]]:
    """Le (uf, municipio, cep, endereco) do dataset anotado.

    O cep sai da coluna `cep` quando existe, senao de `meta ->> '$.cep'`: o
    dataset nem sempre traz cep (imoveis_uniao, censo_escolar), o que vira None.
    Municipio e cep vao crus, porque o geocodebr padroniza o input.
    """
    if not caminho.is_file():
        raise SystemExit(f"base nao encontrada: {caminho}")
    try:
        with sqlite3.connect(f"file:{caminho}?mode=ro", uri=True) as conexao:
            info = cast(
                list[tuple[int, str, str, int, str | None, int]],
                conexao.execute("pragma table_info(enderecos)").fetchall(),
            )
            colunas = {nome for _, nome, *_ in info}
            faltando = {"uf", "municipio", "endereco"} - colunas
            if faltando:
                raise SystemExit(
                    f"{caminho} sem as colunas {sorted(faltando)} em 'enderecos'"
                )
            if "cep" not in colunas and "meta" not in colunas:
                raise SystemExit(f"{caminho} sem 'cep' nem 'meta' em 'enderecos'")
            if "cep" in colunas:
                return cast(
                    list[tuple[str, str | None, str | None, str]],
                    conexao.execute(
                        "select uf, municipio, cep, endereco from enderecos where trim(coalesce(endereco, '')) <> ''"
                    ).fetchall(),
                )
            return cast(
                list[tuple[str, str | None, str | None, str]],
                conexao.execute(
                    "select uf, municipio, json_extract(meta, '$.cep'), endereco from enderecos where trim(coalesce(endereco, '')) <> ''"
                ).fetchall(),
            )
    except sqlite3.Error as erro:
        raise SystemExit(f"falha ao ler {caminho}: {erro}") from erro


def sortear(enderecos: pl.DataFrame, n: int, sal: str) -> pl.DataFrame:
    """Sorteia `n` linhas por hash: a mesma amostra volta, e `--sal` gera holdout."""
    if enderecos.height <= n:
        return enderecos
    return (
        enderecos.with_columns(
            ordem=pl.concat_str([pl.col("endereco"), pl.lit(sal)], separator="~").hash(
                seed=0
            )
        )
        .sort("ordem")
        .head(n)
        .drop("ordem")
    )


def segmentar(tagger: Path, enderecos: Sequence[str]) -> list[list[tuple[str, str]]]:
    """Segmenta com o CRF de Python, que e o mesmo modelo do binario Rust."""
    crf = modelo_crf.carregar_tagger(tagger)
    extrator = ExtratorFeature()
    return [
        [(s["tipo"], s["valor"]) for s in modelo_crf.segmentar(crf, extrator, endereco)]
        for endereco in tqdm(enderecos, desc="segmentando", unit="end")
    ]


def montar_avaliacao(
    amostra: pl.DataFrame,
    segs: list[list[tuple[str, str]]],
    cache: dict[Tupla, str] | None = None,
    caminho_cache: Path | None = None,
) -> Avaliacao:
    linhas_por_tipo: dict[str, list[int]] = collections.defaultdict(list)
    for i, segmentos in enumerate(segs):
        for tipo in dict.fromkeys(tipo for tipo, _ in segmentos):
            linhas_por_tipo[tipo].append(i)
    return Avaliacao(
        estado=cast(list[str], amostra["estado"].to_list()),
        municipio=cast(list[str], amostra["municipio"].to_list()),
        cep=[
            cep_limpo(valor)
            for valor in cast(list[str | None], amostra["cep"].to_list())
        ],
        segs=segs,
        linhas_por_tipo=dict(linhas_por_tipo),
        cache=dict(cache or {}),
        tuplas=[TUDO_NULO] * len(segs),
        etapas=[],
        caminho_cache=caminho_cache,
    )


def caminho_politica(nome: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", nome):
        raise SystemExit(f"nome de politica invalido: {nome!r}")
    return PASTA_POLITICAS / f"{nome}.json"


def regras_para_json(regras: Regras) -> list[dict[str, object]]:
    """Serializa a decision list preservando o aninhamento, nao o texto."""
    return [
        {
            "termos": [
                {
                    "atomo": str(termo.atomo),
                    "valor": termo.valor,
                    "negado": termo.negado,
                }
                for termo in regra.termos
            ],
            "campo": str(regra.campo),
            "se_preenchido": str(regra.se_preenchido),
        }
        for regra in regras
    ]


def regras_de_json(dados: object) -> Regras:
    """Le a politica do json."""
    if not isinstance(dados, list):
        raise SystemExit(f"regra invalida em {dados!r}: esperava lista")
    regras: list[Regra] = []
    for bruto in cast(list[object], dados):
        if not isinstance(bruto, dict):
            raise SystemExit(f"regra invalida em {bruto!r}: esperava objeto")
        item = cast(dict[str, object], bruto)
        termos = tuple(
            Termo(
                Atomo(str(termo["atomo"])),
                cast(str | None, termo.get("valor")),
                bool(termo.get("negado", False)),
            )
            for termo in cast(list[dict[str, object]], item.get("termos", []))
        )
        regras.append(
            Regra(
                termos,
                Campo(str(item.get("campo", Campo.IGNORAR))),
                SePreenchido(str(item.get("se_preenchido", SePreenchido.MANTER))),
            )
        )
    return tuple(regras)


def ler_politica(nome: str) -> Politica:
    """Le a politica gravada por `gravar_politica`."""
    caminho = caminho_politica(nome)
    try:
        dados = cast(dict[str, object], json.loads(caminho.read_text()))
        regras = cast(dict[str, object], dados["politica"])
        return {tipo: regras_de_json(regras[tipo]) for tipo in TIPOS_SEGMENTO}
    except OSError as erro:
        raise SystemExit(f"falha ao ler {caminho}: {erro}") from erro
    except (
        json.JSONDecodeError,
        KeyError,
        TypeError,
        AttributeError,
        ValueError,
    ) as erro:
        raise SystemExit(f"politica invalida em {caminho}: {erro}") from erro


def gravar_politica(nome: str, pol: Politica, resumo: dict[str, object]) -> Path:
    """Grava a politica (uma lista de regras por tipo) com a amostra e o score."""
    caminho = caminho_politica(nome)
    _ = caminho.parent.mkdir(parents=True, exist_ok=True)
    _ = caminho.write_text(
        json.dumps(
            {
                "politica": {
                    tipo: regras_para_json(pol[tipo]) for tipo in TIPOS_SEGMENTO
                },
                **resumo,
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return caminho


def imprimir_politica(pol: Politica, mudadas: set[str], titulo: str) -> None:
    print(f"\n{titulo}")
    for tipo in TIPOS_SEGMENTO:
        marca = "*" if tipo in mudadas else " "
        print(f"  {marca} {tipo:18s} {regras_para_texto(pol[tipo])}")


def imprimir_score(rotulo: str, etapas: Sequence[str]) -> tuple[float, float]:
    linear, ndcg, distribuicao = pontuar(etapas)
    print(f"\n{rotulo}: score linear {linear:.2f}  ndcg {ndcg:.2f}")
    print(
        "  "
        + ", ".join(
            f"{categoria}={quantidade / len(etapas):.1%}"
            for categoria, quantidade in distribuicao.items()
            if quantidade
        )
    )
    return linear, ndcg


def fixar_partida(av: Avaliacao, pol: Politica) -> int:
    """Poem `pol` no estado da avaliacao; devolve as tuplas novas geocodificadas."""
    av.definir(pol, range(len(av)))
    novas = geocodificar(av.cache, av.tuplas, av.caminho_cache)
    av.fixar_etapas()
    return novas


def tagger_mais_recente(pasta: Path = PASTA_MODELOS) -> Path:
    """Tagger treinado mais recente em `pasta`: nao ha versao fixa no codigo."""
    candidatos = sorted(
        pasta.glob("tagger*.crf"), key=lambda caminho: caminho.stat().st_mtime
    )
    if not candidatos:
        raise SystemExit(f"nenhum tagger em {pasta}: treine com `uv run crf treinar`")
    return candidatos[-1]


app = typer.Typer(no_args_is_help=True, add_completion=False)


@app.command()
def main(
    base: Annotated[
        Path, typer.Option(help="dataset anotado (sqlite) ou parquet")
    ] = BASE_PADRAO,
    n: Annotated[int, typer.Option(help="linhas sorteadas da base")] = 5000,
    sal: Annotated[
        str, typer.Option(help="muda a amostra mantendo o tamanho (holdout)")
    ] = "0",
    tagger: Annotated[
        Path | None, typer.Option(help="padrao: o mais recente em data/modelos")
    ] = None,
    inicio: Annotated[str, typer.Option(help="politica salva de onde partir")] = "",
    varreduras: Annotated[int, typer.Option(help="0 apenas avalia")] = 8,
    top: Annotated[int, typer.Option(help="candidatas mostradas por varredura")] = 3,
    minimo: Annotated[
        float,
        typer.Option(
            help="delta minimo (pp) para aceitar uma troca; abaixo disso e ruido de amostra"
        ),
    ] = 0.2,
    usar_cache: Annotated[
        bool, typer.Option(help="le e grava o cache de tuplas em disco")
    ] = True,
    cache: Annotated[
        Path,
        typer.Option(
            help="parquet das tuplas ja geocodificadas, reusado entre execucoes"
        ),
    ] = CACHE_PADRAO,
    reinicios: Annotated[
        int,
        typer.Option(
            help="chutes aleatorios apos a otimizacao, compartilhando o cache"
        ),
    ] = 0,
    salvar: Annotated[
        str, typer.Option(help="nome do json em data/politicas")
    ] = "otimizada",
) -> None:
    """Otimiza a politica pos-CRF contra o geocodebr (coordinate ascent)."""
    modelo = tagger or tagger_mais_recente()
    print(f"tagger: {modelo}", flush=True)
    inicio_execucao = time.perf_counter()
    limitar_duckdb()

    amostra = sortear(ler_base(base), n, sal)
    segs = segmentar(modelo, cast(list[str], amostra["endereco"].to_list()))
    caminho_cache = cache if usar_cache else None
    tuplas_disco = ler_cache(caminho_cache) if caminho_cache else {}
    av = montar_avaliacao(amostra, segs, tuplas_disco, caminho_cache)
    print(
        f"cache: {len(tuplas_disco)} tuplas de {caminho_cache or '(desligado)'}",
        flush=True,
    )
    contagem = collections.Counter(tipo for segmentos in segs for tipo, _ in segmentos)
    print(
        f"\namostra: {len(av)} linhas de {base} (sal={sal}), "
        + ", ".join(
            f"{tipo}={quantidade / len(av):.1%}"
            for tipo, quantidade in contagem.most_common(6)
        ),
        flush=True,
    )

    pol = ler_politica(inicio) if inicio else INICIAL
    _ = fixar_partida(av, pol)
    print(
        f"baseline: {len(av.cache)} tuplas, {time.perf_counter() - inicio_execucao:.0f}s",
        flush=True,
    )
    imprimir_politica(pol, set(), "politica de partida")
    linear_inicial, ndcg_inicial = imprimir_score("partida", av.etapas)

    pol, alteracoes = otimizar(av, pol, varreduras, top, minimo)
    melhores: list[int] = []
    if reinicios:
        massa = {tipo: len(linhas) for tipo, linhas in av.linhas_por_tipo.items()}
        # Melhor (score, politica, etapas, alteracoes) ate agora; as etapas
        # voltam a valer no fim, para imprimir e gravar a melhor politica.
        melhor: tuple[
            float, Politica, list[str], list[tuple[int, str, Regras, float]]
        ] = (
            pontuar(av.etapas)[0],
            pol,
            list(av.etapas),
            alteracoes,
        )
        for numero in range(1, reinicios + 1):
            repos = perturbar(melhor[1], random.Random(numero), massa)
            chute = ", ".join(
                f"{tipo} -> {regras_para_texto(repos[tipo])}"
                for tipo in TIPOS_SEGMENTO
                if repos[tipo] != melhor[1][tipo]
            )
            print(f"\n[reinicio {numero}/{reinicios}] chute: {chute}", flush=True)
            novas = fixar_partida(av, repos)
            repos, alt_reinicio = otimizar(av, repos, varreduras, top, minimo)
            linear_reinicio = pontuar(av.etapas)[0]
            print(
                f"[reinicio {numero}/{reinicios}] {novas} tuplas novas, score linear {linear_reinicio:.2f}",
                flush=True,
            )
            if linear_reinicio > melhor[0] + 1e-9:
                melhor = (linear_reinicio, repos, list(av.etapas), alt_reinicio)
                melhores.append(numero)
                print(f"[reinicio {numero}] nova melhor politica", flush=True)
        pol, alteracoes = melhor[1], melhor[3]
        av.etapas = melhor[2]
    imprimir_politica(pol, {tipo for _, tipo, _, _ in alteracoes}, "politica otimizada")
    linear_final, ndcg_final = imprimir_score("otimizada", av.etapas)

    caminho = gravar_politica(
        salvar,
        pol,
        {
            "amostra": {"base": str(base), "n": len(av), "sal": sal},
            "modelo": str(modelo),
            "resultado": {
                "score_linear": round(linear_final, 3),
                "ndcg": round(ndcg_final, 3),
                "delta_pp": round(linear_final - linear_inicial, 3),
                "alteracoes": [
                    {
                        "varredura": v,
                        "tipo": t,
                        "regras": regras_para_texto(r),
                        "delta_pp": round(d, 4),
                    }
                    for v, t, r, d in alteracoes
                ],
                "reinicios": {"executados": reinicios, "melhores": melhores},
            },
        },
    )
    print(
        f"\nscore linear {linear_inicial:.2f} -> {linear_final:.2f}, ndcg {ndcg_inicial:.2f} -> {ndcg_final:.2f}"
    )
    if reinicios:
        print(f"reinicios: {reinicios}, chutes que melhoraram: {melhores or 'nenhum'}")
    print(f"politica gravada em: {caminho}")
    print(f"fim: {time.perf_counter() - inicio_execucao:.0f}s")


if __name__ == "__main__":
    app()
