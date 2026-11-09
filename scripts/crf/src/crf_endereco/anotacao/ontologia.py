"""Tipos de segmento que a LLM pode emitir.

O rótulo diz **o que é**; o mapeamento para um campo (CNEFE, `Endereco`) é
decidido no `segmento_como_endereco`, não aqui. Duas consequências dessa
separação:

- `referencia` e `denominacao` são **marcadores que abrem** um trecho; o nome
  que vem depois recebe o próprio tipo (`recurso_natural`, `logradouro`,
  `nucleo_rural`, ...). Só cai em `ponto_referencia` quando não é lugar nenhum.
- `nucleo_rural` é uma especialização de `localidade` (mesmo destino, léxico e
  prioridade de candidatos diferentes).
"""

TIPOS_SEGMENTO = [
    "logradouro",
    "numero",
    "complemento",
    "parcela",
    "empreendimento",
    "localidade",
    "nucleo_rural",
    "recurso_natural",
    "referencia",
    "ponto_referencia",
    "denominacao",
    "quilometragem_via",
    "cep",
    "municipio",
    "uf",
    "cadastro",
    "ruido",
    "outros",
]
