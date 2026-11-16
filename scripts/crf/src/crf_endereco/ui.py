"""Saida no terminal: o console unico, a barra de progresso e as cores dos tipos."""

import zlib

from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    TextColumn,
    TimeElapsedColumn,
)

console = Console()


def progresso(*, stderr: bool = False) -> Progress:
    """Barra de progresso com o layout padrao do projeto."""
    return Progress(
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        console=Console(stderr=True) if stderr else console,
    )


# Cor estavel por tipo de segmento: o mesmo tipo tem a mesma cor no `explicar`
# e no relatorio de avaliacao.
CORES_TIPO = {
    "logradouro": "cyan",
    "numero": "bright_magenta",
    "complemento": "yellow",
    "parcela": "green",
    "empreendimento": "bright_blue",
    "localidade": "blue",
    "nucleo_rural": "bright_cyan",
    "recurso_natural": "bright_green",
    "referencia": "magenta",
    "ponto_referencia": "bright_yellow",
    "denominacao": "bright_red",
    "quilometragem_via": "color(202)",
    "cep": "red",
    "municipio": "color(99)",
    "uf": "color(135)",
    "cadastro": "color(141)",
    "ruido": "color(243)",
    "outros": "color(109)",
}

# Tipos novos, se surgirem, caem em uma cor estavel derivada do nome.
FALLBACK_CORES = [
    "color(75)",
    "color(214)",
    "color(213)",
    "color(80)",
    "color(171)",
    "color(117)",
    "color(137)",
    "color(179)",
]


def estilo_tipo(tipo: str) -> str:
    """Cor do tipo de segmento, com fallback estavel para tipo desconhecido."""
    return (
        CORES_TIPO.get(tipo)
        or FALLBACK_CORES[zlib.crc32(tipo.encode()) % len(FALLBACK_CORES)]
    )


def estilo_rotulo(rotulo: str) -> str:
    """Estilo de uma etiqueta BIO: `B_` em negrito, `O` apagado."""
    if rotulo == "O":
        return "dim"
    bio, _, tipo = rotulo.partition("_")
    cor = estilo_tipo(tipo.lower() or rotulo.lower())
    return f"bold {cor}" if bio == "B" else cor
