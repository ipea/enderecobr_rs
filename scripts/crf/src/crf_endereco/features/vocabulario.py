"""Vocabulário de termos conhecidos casados sobre um texto já tokenizado."""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from crf_endereco.features.texto import normalize, tokenize

# Trie das palavras: cada nível é uma palavra normalizada do termo. A chave
# sentinela `""` marca onde um termo termina, porque uns termos são prefixo de
# outros (`SANTA RITA` e `SANTA RITA DO PASSA QUATRO`) e nenhuma palavra
# normalizada é vazia.
type Trie = dict[str, Trie]
FIM = ""


class Vocabulario:
    """Conjunto de termos formados por palavras.

    O casamento é sempre o mais à esquerda e o mais longo possível, sem
    sobreposição: com os termos `SANTA RITA` e `SANTA RITA DO PASSA QUATRO`, o
    texto `SANTA RITA DO PASSA QUATRO` casa só o termo longo.

    A busca é feita palavra a palavra sobre a saída de [`casar`], então a
    pontuação do texto fica de fora: `OLHO D'ÁGUA` casa com o termo
    `OLHO D'AGUA`.
    """

    def __init__(self, termos: Iterable[str]) -> None:
        self._trie: Trie = {}
        for termo in termos:
            _adicionar(self._trie, palavras_do_termo(termo))

    def casar(self, palavras: Sequence[str]) -> list[tuple[int, int]]:
        """Intervalos `(início, fim)` das palavras de cada ocorrência."""
        ocorrencias: list[tuple[int, int]] = []
        inicio = 0
        while inicio < len(palavras):
            # Desce o quanto o vocabulário permitir, guardando o último termo
            # completo do caminho — é ele que o casamento longo prefere.
            no = self._trie
            fim: int | None = None
            for posicao in range(inicio, len(palavras)):
                proximo = no.get(palavras[posicao])
                if proximo is None:
                    break
                no = proximo
                if FIM in no:
                    fim = posicao + 1

            if fim is None:
                inicio += 1
            else:
                ocorrencias.append((inicio, fim))
                inicio = fim

        return ocorrencias


def palavras_do_termo(termo: str) -> list[str]:
    """Palavras normalizadas de um termo, na ordem.

    `OLHO D'ÁGUA` vira `["OLHO", "D", "AGUA"]`, a mesma chave que os tokens
    `OLHO`, `D`, `'`, `AGUA` do texto geram na comparação.
    """
    return [
        palavra
        for palavra in (normalize(tok).upper() for tok in tokenize(termo))
        if palavra.isalnum()
    ]


def _adicionar(trie: Trie, palavras: list[str]) -> None:
    if not palavras:
        return
    no = trie
    for palavra in palavras:
        no = no.setdefault(palavra, {})
    no[FIM] = {}
