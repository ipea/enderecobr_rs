"""Saida no terminal: o console unico e a barra de progresso padrao."""

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
