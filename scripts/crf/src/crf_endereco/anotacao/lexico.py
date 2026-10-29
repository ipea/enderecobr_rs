"""Léxico de cabeças e marcadores compartilhado pela anotação e pela migração.

Três listas fechadas: cabeças de núcleo rural, cabeças de feição natural e
cabeças de via, mais os marcadores de referência/denominação. A documentação de
cada uma diz o que ficou de fora e por quê. A fonte das cabeças é
`nom_tipo_seglogr`/`desc_localidade` do CNEFE, conferida contra o dataset.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass

# `\S+` guarda as posições no texto original: o corte é feito por índice, sem
# reconstruir espaços, porque os segmentos têm de continuar verbatim.
PALAVRA = re.compile(r"\S+")

# Conectivos absorvidos pelo marcador quando ainda há nome depois
# (`MARGEM ESQ. **DO** CÓRREGO`, `PRÓXIMO **AO** MERCADO`).
CONECTIVOS = frozenset(
    {
        "A",
        "AO",
        "AOS",
        "AS",
        "COM",
        "DA",
        "DAS",
        "DE",
        "DO",
        "DOS",
        "EM",
        "NA",
        "NAS",
        "NO",
        "NOS",
        "O",
        "OS",
        "PARA",
        "PELA",
        "PELO",
    }
)

# Cabeças de lugar rural/populacional: abre o span e faz parte dele
# (`ALDEIA ITAMARATI 1`, `SITIO MIRADOR`, `FAZENDA SANTA RITA`).
#
# Sítio/fazenda/chácara/estância/granja entram aqui porque o usuário quer
# resolvê-los no pós-processamento, não como `logradouro`: o CNEFE guarda o mesmo
# nome em `nom_seglogr` (tipo FAZENDA/SITIO) e em `desc_localidade`, então a
# escolha entre via e lugar é do mapeamento, não do rótulo.
#
# Ficaram de fora de propósito, com o motivo:
# - `PA <n>`: rodovia estadual do Pará (`PA 124`), código do SPU em imóveis da
#   União do RJ (`PA 44191`) ou a sigla da UF;
# - `NR <n>`: abreviação de "número" da unidade (`GARAGEM NR 12`);
# - `VILA`: bairro urbano (6,46 mi de `desc_localidade`);
# - `RESERVA` sem qualificador: `RESERVA DO ABARÉ` é empreendimento no RJ;
# - `CH` sozinho: é chácara no DF e conjunto habitacional fora dele.
CABECAS_NUCLEO: tuple[str, ...] = (
    "ALDEIA INDIGENA",
    "COMUNIDADE INDIGENA",
    "COMUNIDADE RURAL",
    "PROJETO DE ASSENTAMENTO",
    "ASSENTAMENTO RURAL",
    "COLONIA AGRICOLA",
    "RESERVA EXTRATIVISTA",
    "RESERVA INDIGENA",
    "TERRA INDIGENA",
    "AREA INDIGENA",
    "NUCLEO RURAL",
    "ASSENTAMENTO",
    "ACAMPAMENTO",
    "COMUNIDADE",
    "POVOADO",
    "LUGAREJO",
    "AGROVILA",
    "COLONIA",
    "RIBEIRINHA",
    "RIBEIRINHO",
    "FAZENDA",
    "ESTANCIA",
    "GRANJA",
    "CHACARA",
    "SITIO",
    "ALDEIA",
    "FAZ",
    "SIT",
)

# Feições naturais: nome de rio/córrego/lagoa/morro/serra vira `recurso_natural`
# em qualquer posição. O rótulo diz **o que é**; o papel no endereço (via ou
# localidade) é resolvido no pós-processamento, com sinais que a anotação não
# tem — a regra, medida no corpus e no CNEFE:
#   1. posição: feição antes do `numero` -> logradouro; depois do `numero` ou na
#      cauda -> localidade (15/84 das feições no corpus ocupam slot de via, 69/84
#      slot de localidade);
#   2. CNEFE, na camada de candidatos: `nom_seglogr` casa -> via;
#      `desc_localidade` casa -> localidade (prior: relevo 4,3x localidade —
#      MORRO 301.463 x 70.567 linhas; no Rio, MORRO DO BOREL/DENDE/FORMIGA/
#      TIMBAU somam 13.398 localidades contra ~520 vias);
#   3. fallback: localidade (papel majoritário).
# Exceção de contexto, que fica no léxico: município/UF batizado com nome de rio
# (RIO DE JANEIRO, RIO BRANCO) continua `municipio`/`uf`.
CABECAS_RECURSO_NATURAL: tuple[str, ...] = (
    "PARQUE NACIONAL",
    "RESERVA BIOLOGICA",
    "CACHOEIRA",
    "IGARAPE",
    "CORREGO",
    "RIACHO",
    "LAGOA",
    "ENSEADA",
    "GROTA",
    "SERRA",
    "MORRO",
    "ILHA",
    "PRAIA",
    "BAIA",
    "LAGO",
    "RIO",
    "CRG",
)

CABECAS_VIA: tuple[str, ...] = (
    "AVENIDA",
    "ALAMEDA",
    "TRAVESSA",
    "ESTRADA",
    "RODOVIA",
    "SERVIDAO",
    "PASSAGEM",
    "CORREDOR",
    "ESCADARIA",
    "CAMINHO",
    "VICINAL",
    "LADEIRA",
    "ACESSO",
    "RAMAL",
    "LINHA",
    "PRACA",
    "LARGO",
    "VIELA",
    "BECO",
    "RUA",
    "AVE",
    "TRAV",
    "EST",
    "ROD",
    "AV",
    "AL",
    "TV",
    "PC",
    "BR",
    "R",
)

# Marcadores que abrem uma referência, com o nome logo depois. Não há família
# compositiva/relativa: o marcador marca, o nome recebe o próprio tipo e o
# pós-processamento decide se o conjunto é parte do endereço ou aponta para fora.
MARCADORES_REFERENCIA: tuple[str, ...] = (
    "MARGEM ESQUERDA",
    "MARGEM DIREITA",
    "MARGEM ESQ",
    "MARGEM DIR",
    "MARGEM DO",
    "MARGEM DA",
    "MARGEM DE",
    "MARGENS DO",
    "MARGENS DA",
    "MARGENS",
    "MARGEM",
    "LUGAR DENOMINADO",
    "LOCAL DENOMINADO",
    "LUGAR CHAMADO",
    "LUGAR CONHECIDO COMO",
    "LOCAL CONHECIDO COMO",
    "CONHECIDO COMO",
    "CONHECIDA COMO",
    "DENOMINADO",
    "DENOMINADA",
    "PROLONGAMENTO",
    "PROXIMO A",
    "PROXIMO AO",
    "PROXIMA A",
    "PROXIMO",
    "PROXIMA",
    "PROXIMOA",
    "PERTO DE",
    "PERTO DO",
    "PERTO DA",
    "PERTO",
    "AO LADO DE",
    "AO LADO DO",
    "AO LADO DA",
    "AO LADO",
    "DO LADO DE",
    "DO LADO",
    "EM FRENTE A",
    "EM FRENTE AO",
    "EM FRENTE",
    "NA FRENTE DE",
    "NA FRENTE",
    "DEFRONTE",
    "ENTRE",
    "DEPOIS DE",
    "DEPOIS DO",
    "DEPOIS DA",
    "DEPOIS",
    "APOS",
    "ANTES DE",
    "ANTES DO",
    "ANTES DA",
    "ANTES",
    "POR TRAS DE",
    "POR TRAS",
    "ATRAS DE",
    "ATRAS",
    "ESQUINA COM",
    "ESQUINA",
    "JUNTO A",
    "JUNTO AO",
    "JUNTO DE",
    "JUNTO",
    "SEGUIDO DE",
    "SENTIDO",
    "DIRECAO",
    "RUMO A",
    "ATE",
    "NA RUA",
    "NA AVENIDA",
    "NO FUNDO DA",
    "NO FUNDO DE",
    "NO FUNDO",
    "FUNDO DA",
    "ACIMA DA",
    "ABAIXO DA",
    "LADO IMPAR",
    "LADO PAR",
    "PARTINDO DE",
    "SAINDO DE",
    "VINDO DE",
)

MARCADORES_DENOMINACAO: tuple[str, ...] = (
    "ANTIGA DENOMINACAO",
    "NOVA DENOMINACAO",
    "ANTIGO NOME",
    "ANTIGA",
    "ANTIGO",
    "ATUALMENTE",
    "ATUAL",
    "HOJE",
    "ANT",
)


@dataclass(frozen=True)
class Referencia:
    """Um trecho de referência partido em marcador e nome."""

    marcador: str  # verbatim, com os conectivos contíguos
    resto: str  # verbatim, sem o marcador
    tipo_resto: str  # rótulo do nome que segue


def normalizar(texto: str) -> str:
    """Maiúsculas sem acento, preservando a pontuação."""
    decomposto = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in decomposto if not unicodedata.combining(c)).upper()


def chave(palavra: str) -> str:
    """Forma comparável de uma palavra: sem acento, pontuação e ordinal.

    O ordinal sai antes da decomposição NFKD: `nº` decompõe para `no` e, sem
    isso, `PROXIMO AO Nº 52` absorveria o `nº` como conectivo.
    """
    sem_ordinal = palavra.replace("º", "").replace("ª", "")
    return re.sub(r"[^A-Z0-9]", "", normalizar(sem_ordinal))


def _palavras(valor: str) -> list[tuple[int, int, str]]:
    """(início, fim, chave) de cada palavra, nas posições do texto original."""
    return [(m.start(), m.end(), chave(m.group())) for m in PALAVRA.finditer(valor)]


def _indice_por_tamanho(termos: Sequence[str]) -> dict[int, frozenset[str]]:
    por_tamanho: dict[int, set[str]] = {}
    for termo in termos:
        canonico = " ".join(chave(palavra.group()) for palavra in PALAVRA.finditer(termo))
        por_tamanho.setdefault(len(canonico.split()), set()).add(canonico)
    return {tamanho: frozenset(conjunto) for tamanho, conjunto in por_tamanho.items()}


_INDICE_NUCLEO = _indice_por_tamanho(CABECAS_NUCLEO)
_INDICE_NATURAL = _indice_por_tamanho(CABECAS_RECURSO_NATURAL)
_INDICE_VIA = _indice_por_tamanho(CABECAS_VIA)
_INDICE_REFERENCIA = _indice_por_tamanho(MARCADORES_REFERENCIA)
_INDICE_DENOMINACAO = _indice_por_tamanho(MARCADORES_DENOMINACAO)


def _casa_inicio(
    valor: str, indice: dict[int, frozenset[str]]
) -> tuple[int, int] | None:
    """Quantas palavras o termo consome e até que índice do texto (verbatim)."""
    palavras = _palavras(valor)
    for tamanho in sorted(indice, reverse=True):
        if tamanho > len(palavras):
            continue
        candidato = " ".join(palavra[2] for palavra in palavras[:tamanho])
        if candidato in indice[tamanho]:
            return tamanho, palavras[tamanho - 1][1]
    return None


def tem_cabeca_nucleo(valor: str) -> bool:
    """Se o valor abre com uma cabeça de lugar rural/populacional."""
    return _casa_inicio(valor, _INDICE_NUCLEO) is not None


def tem_cabeca_recurso(valor: str) -> bool:
    """Se o valor abre com uma feição natural (rio, córrego, lagoa, serra...)."""
    return _casa_inicio(valor, _INDICE_NATURAL) is not None


def separar_marcador(valor: str, termos: Sequence[str]) -> tuple[str, str] | None:
    """Parte `valor` em (marcador, resto), ambos verbatim.

    O marcador é o termo mais longo que abre o valor, mais os conectivos que
    vierem em seguida — desde que sobre ao menos uma palavra para o nome:
    `MARGEM ESQ. DO` + `CORREGO QUISSAMAR`.
    """
    casa = _casa_inicio(valor, _indice_por_tamanho(termos))
    if casa is None:
        return None
    palavras = _palavras(valor)
    consumidas = casa[0]
    while consumidas + 1 < len(palavras) and palavras[consumidas][2] in CONECTIVOS:
        consumidas += 1
    if consumidas >= len(palavras):
        return None
    return valor[: palavras[consumidas - 1][1]], valor[palavras[consumidas][0] :]


def tipo_do_nome(resto: str) -> str:
    """Rótulo do nome que segue um marcador de referência.

    Lugar reconhecível recebe o tipo próprio; o que não é via, lugar nem feição
    natural é `ponto_referencia` (o balde do conteúdo de referência).
    """
    if tem_cabeca_nucleo(resto):
        return "nucleo_rural"
    if tem_cabeca_recurso(resto):
        return "recurso_natural"
    if _casa_inicio(resto, _INDICE_VIA) is not None:
        return "logradouro"
    return "ponto_referencia"


def classificar_referencia(valor: str) -> Referencia | None:
    """Classifica um trecho de referência; `None` quando não há marcador."""
    partido = separar_marcador(valor, MARCADORES_REFERENCIA)
    if partido is None:
        return None
    marcador, resto = partido
    return Referencia(
        marcador=marcador, resto=resto, tipo_resto=tipo_do_nome(resto)
    )


def classificar_denominacao(valor: str) -> tuple[str, str, str | None] | None:
    """Parte uma denominação em (marcador, resto, tipo do resto).

    `tipo` é `None` quando o resto não é um lugar reconhecível — aí o caso é
    `stale` e volta para a LLM.
    """
    partido = separar_marcador(valor, MARCADORES_DENOMINACAO)
    if partido is None:
        return None
    marcador, resto = partido
    if tem_cabeca_nucleo(resto):
        return marcador, resto, "nucleo_rural"
    if tem_cabeca_recurso(resto):
        return marcador, resto, "recurso_natural"
    if _casa_inicio(resto, _INDICE_VIA) is not None:
        return marcador, resto, "logradouro"
    return marcador, resto, None
