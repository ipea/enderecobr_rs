"""Comando de busca de hiperparametros."""

from crf_endereco.modelos.tuning import tunar as executar


def tunar() -> None:
    """Roda o GridSearch de hiperparametros do CRF."""
    executar()
