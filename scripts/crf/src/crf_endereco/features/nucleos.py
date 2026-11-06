"""Nomes de nucleos rurais conhecidos como feature de lexico.

A lista e curada por duas fontes: o dataset anotado (pureza da etiqueta quando o
token abre um nome) e o CNEFE (1,1e8 de enderecos), que usa esses nomes como
`nom_tipo_seglogr` e mostra a frequencia nacional de cada um e quantas vezes ele
aparece como nome de via (risco de falso positivo).

Ficaram de fora:

- `LINHA` e `RAMAL`: o CNEFE os usa como tipo de via (3,2e5 e 3,6e5 registros) e
  no dataset sao 5% e 2% `nucleo_rural`;
- `VILA` (localidade), `GLEBA` (`parcela`), `PARQUE`, `LOTEAMENTO`, `PROJETO`,
  `RETIRO`, `NUCLEO` e `TERRA` soltos: no CNEFE sao mais nome de via que tipo, e
  no dataset ficam abaixo de 40%;
- `GRANJA`: e nome de municipio (`Granja - CE`) antes de ser nucleo;
- abreviacao entra so quando o corpus sustenta: `FAZ` (83%) e `SIT` (92%) sim;
  `CH` (21%, Setor Habitacional), `COL` (0%), `ASSENT`/`LUG` (25%), `VILAR`
  (0%, sobrenome), `ALD`, `ESTANC`, `AGROV`, `GR` nao.
"""

from __future__ import annotations

from collections.abc import Sequence
from functools import lru_cache

from crf_endereco.features.municipios import Trie, marcar_nomes, trie_de_nomes
from crf_endereco.features.texto import SIGLAS_ESTADOS, normalize

NUCLEOS_RURAIS = (
    "COMUNIDADE",
    "POVOADO",
    "FAZENDA",
    "FAZ",
    "SITIO",
    "SIT",
    "ALDEIA",
    "COLONIA",
    "CHACARA",
    "ESTANCIA",
    "ASSENTAMENTO",
    "AGROVILA",
    "LUGAREJO",
    "VILAREJO",
    "ACAMPAMENTO",
    "NUCLEO RURAL",
    "TERRA INDIGENA",
)

# `CHACARA 51` e `SITIO 3` sao `parcela`; nos outros nucleos o nome pode ser
# numeral (`AGROVILA 2`, `AGROVILA 14` sao `nucleo_rural` no dataset).
CABECAS_DE_PARCELA = frozenset({"CHACARA", "SITIO"})

# Nome que e identificador de terra ou pedaco de `S/N` nao e nome de nucleo
# (`CHACARA LOTE 01` continua `parcela`).
NAO_E_NOME = frozenset({"N", "S", "LOTE", "LT", "GLEBA", "GLE", "QUADRA", "QD", "Q"})


@lru_cache(maxsize=1)
def construir_trie() -> Trie:
    return trie_de_nomes(NUCLEOS_RURAIS)


def marcar_nucleos(sent: Sequence[str], trie: Trie) -> list[str | None]:
    """Marca a cabeca de um nucleo rural conhecido seguido do nome dele.

    O rotulo exige cabeca **mais** nome: um `POVOADO` solto e `ruido`, entao o
    nome so vale quando ha um token alfabetico (ou numeral, fora das cabecas de
    `parcela`) depois dele. Sigla de estado tambem derruba a marca: `ESTANCIA SE`
    e `municipio`. Devolve `nucleo_B`/`nucleo_I` como o `marcar_nomes`.
    """
    marcas = marcar_nomes(sent, trie, "nucleo")

    for i, marca in enumerate(marcas):
        if marca is None or not marca.endswith("_B"):
            continue
        fim = i
        while fim + 1 < len(marcas) and marcas[fim + 1] is not None:
            fim += 1
        proximo = next((tok for tok in sent[fim + 1 :] if tok.isalnum()), None)
        palavras = {normalize(tok).upper() for tok in sent[i : fim + 1]}
        if (
            proximo is None
            or proximo.upper() in SIGLAS_ESTADOS
            or proximo.upper() in NAO_E_NOME
            or (not proximo[0].isalpha() and palavras & CABECAS_DE_PARCELA)
        ):
            for j in range(i, fim + 1):
                marcas[j] = None

    return marcas
