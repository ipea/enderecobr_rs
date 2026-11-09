"""Roda os exemplos das docstrings públicas contra o módulo em execução.

As docstrings moram no Rust (`src/*.rs`), então `--doctest-glob` não as alcança:
elas só existem no objeto em tempo de execução.
"""

import doctest
import inspect
from collections.abc import Iterator, Mapping
from typing import cast

import enderecobr


def _membros(objeto: object = enderecobr) -> Mapping[str, object]:
    """Nomes públicos de um módulo, classe ou objeto."""
    return cast("Mapping[str, object]", vars(objeto))


def _documentados() -> Iterator[tuple[str, object]]:
    """Funções, classes e métodos públicos expostos pelo módulo."""
    for nome, objeto in _membros().items():
        if nome.startswith("_"):
            continue
        yield nome, objeto
        if isinstance(objeto, type):
            for nome_membro, membro in _membros(objeto).items():
                if not nome_membro.startswith("_"):
                    yield f"{nome}.{nome_membro}", membro


def test_docstrings():
    parser = doctest.DocTestParser()
    runner = doctest.DocTestRunner()
    # O mesmo namespace que `from enderecobr import *` daria: os exemplos usam os
    # nomes públicos direto.
    publicos = {"enderecobr": enderecobr, **_membros()}
    exemplos = 0

    for nome, objeto in _documentados():
        texto = inspect.getdoc(objeto)
        if not texto or ">>>" not in texto:
            continue
        teste = parser.get_doctest(texto, dict(publicos), nome, nome, 0)
        exemplos += len(teste.examples)
        _ = runner.run(teste)

    assert exemplos > 0, "nenhum exemplo de docstring encontrado"
    if runner.failures:
        _ = runner.summarize(verbose=True)
    assert runner.failures == 0
