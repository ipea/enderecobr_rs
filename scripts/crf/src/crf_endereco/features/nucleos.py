"""Cabeças de núcleo rural conhecidas como feature de léxico.

A lista é curada por duas fontes: o dataset anotado (pureza da etiqueta quando o
token abre um nome) e o CNEFE (1,1e8 de endereços), que usa esses nomes como
`nom_tipo_seglogr` e mostra a frequência nacional de cada um e quantas vezes ele
aparece como nome de via (risco de falso positivo).

Ficaram de fora:

- `LINHA` e `RAMAL`: o CNEFE os usa como tipo de via (3,2e5 e 3,6e5 registros) e
  no dataset são 5% e 2% `nucleo_rural`;
- `VILA` (localidade), `GLEBA` (`parcela`), `PARQUE`, `LOTEAMENTO`, `PROJETO`,
  `RETIRO`, `NUCLEO` e `TERRA` soltos: no CNEFE são mais nome de via que tipo, e
  no dataset ficam abaixo de 40%;
- `GRANJA`: é nome de município (`Granja - CE`) antes de ser núcleo;
- abreviação entra só quando o corpus sustenta: `FAZ` (83%) e `SIT` (92%) sim;
  `CH` (21%, Setor Habitacional), `COL` (0%), `ASSENT`/`LUG` (25%), `VILAR`
  (0%, sobrenome), `ALD`, `ESTANC`, `AGROV`, `GR` não.
"""

from __future__ import annotations

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
