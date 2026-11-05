"""Nomes de nucleos rurais conhecidos como feature de lexico.

A lista e curada pelo dataset anotado: cada entrada so entra se o token que abre
o nome recebe `nucleo_rural` na grande maioria das ocorrencias (>=78%, medido
com `crf avaliar`), porque um lexico ruidoso custa caro em `logradouro` e
`localidade`, que sao as classes majoritarias.

Ficaram de fora, com a taxa de acerto medida:

- `LINHA` (5%) e `RAMAL` (2%): sao tipo de via, nao de nucleo;
- `GLEBA` (1%): e `parcela`;
- `NUCLEO` (38%), `TERRA` (68%), `INDIGENA` (90% isolada, 83% no par): so valem
  no nome composto, que esta na lista;
- `GRANJA` (62%): o token e nome de municipio (`Granja - CE`) antes de ser
  nucleo;
- `ACAMPAMENTO` (25%), `RIBEIRINHA` (33%), `MUTIRAO` (0%), `PROJETO` (11%),
  `VILA`/`CONJUNTO`/`LOTEAMENTO`/`RESIDENCIAL` (<=2%): `localidade` ou
  `empreendimento`.

Abreviacao entra so quando o corpus sustenta: `FAZ` (83%) e `SIT` (92%) sim,
`ST`/`CH`/`POV`/`COM`/`ASSENT` nao.
"""

from __future__ import annotations

from collections.abc import Sequence
from functools import lru_cache

from crf_endereco.features.municipios import Trie, marcar_nomes, trie_de_nomes

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
    "NUCLEO RURAL",
    "TERRA INDIGENA",
)


@lru_cache(maxsize=1)
def construir_trie() -> Trie:
    return trie_de_nomes(NUCLEOS_RURAIS)


def marcar_nucleos(sent: Sequence[str], trie: Trie) -> list[str | None]:
    """Marca o cabeca de um nucleo rural conhecido seguido do nome dele.

    O rotulo exige cabeca **mais** nome: `CHACARA 51` e `parcela` e um `POVOADO`
    solto e `ruido`, entao o nome so vale quando o proximo token alfabetico vem
    depois dele. Devolve `nucleo_B`/`nucleo_I` como o `marcar_nomes`.
    """
    marcas = marcar_nomes(sent, trie, "nucleo")

    for i, marca in enumerate(marcas):
        if marca is None or not marca.endswith("_B"):
            continue
        fim = i
        while fim + 1 < len(marcas) and marcas[fim + 1] is not None:
            fim += 1
        proximo = next((tok for tok in sent[fim + 1 :] if tok.isalnum()), None)
        if proximo is None or not proximo[0].isalpha():
            for j in range(i, fim + 1):
                marcas[j] = None

    return marcas
