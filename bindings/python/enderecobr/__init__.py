"""Padroniza e estrutura endereços brasileiros.

Attributes
----------
MODEL_DOWNLOAD_PATH : str
    URL de onde o modelo padrão é baixado.
NOME_ARQUIVO_MODELO : str
    Nome do arquivo do modelo dentro do diretório de cache.
NOME_DIRETORIO_CACHE : str
    Nome do diretório da biblioteca dentro do cache do sistema.
VERSAO_MODELO : str
    Versão do modelo padrão: é o subdiretório usado no cache.
VAR_AMBIENTE_MODELO : str
    Nome da variável de ambiente que aponta para o modelo
    (`ENDERECOBR_MODELO`).
VAR_AMBIENTE_SEM_DOWNLOAD : str
    Nome da variável de ambiente que desabilita o download, útil em CI
    (`ENDERECOBR_MODELO_SEM_DOWNLOAD`).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import cast
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

import enderecobr.enderecobr as _extensao
from enderecobr.enderecobr import *  # noqa: F403, RUF100


def _variavel_ambiente_ativa(nome: str) -> bool:
    """Variável definida com um valor considerado "ligado"."""
    return os.environ.get(nome, "") not in ("", "0", "false")


def obter_modelo(path_modelo: str | Path | None = None) -> Path:
    """Resolve o caminho do modelo padrão e garante que o arquivo exista,
    baixando-o na primeira chamada.

    Usa a mesma ordem de prioridade de `obter_caminho_modelo` e só baixa o
    modelo quando o arquivo está ausente ou vazio. O download pode ser desativado
    com a variável de ambiente `ENDERECOBR_MODELO_SEM_DOWNLOAD=1` (útil em CI):
    nesse caso o caminho é devolvido sem a garantia de existir.

    Parameters
    ----------
    path_modelo : str or pathlib.Path or None, optional
        Arquivo ou diretório do modelo. Informado, tem prioridade sobre a
        variável de ambiente e sobre o cache.

    Returns
    -------
    pathlib.Path
        Caminho do arquivo `.crf`, baixado se necessário.

    Raises
    ------
    RuntimeError
        Se o download falhar (HTTP, rede ou timeout).
    OSError
        Se o diretório de destino não puder ser criado ou o arquivo não puder
        ser gravado.

    Examples
    --------
    >>> from enderecobr import SeparadorEndereco, obter_modelo
    >>> sep = SeparadorEndereco.carregar(obter_modelo())  # doctest: +SKIP
    >>> sep.segmentar('av n sra copacabana, 123').segmentos[0].tipo  # doctest: +SKIP
    TipoSegmento.Logradouro

    Notes
    -----
    - Faz uma requisição HTTP (timeout de 60 s) apenas quando precisa baixar e
      grava num arquivo temporário ao lado do destino antes de renomear, então
      um download interrompido não deixa modelo truncado no lugar.
    - O caminho devolvido pode ser passado direto para `SeparadorEndereco.carregar`.
    """
    caminho = _extensao.obter_caminho_modelo(path_modelo)

    if caminho.is_file() and caminho.stat().st_size > 0:
        return caminho

    if _variavel_ambiente_ativa(_extensao.VAR_AMBIENTE_SEM_DOWNLOAD):
        return caminho

    url = _extensao.MODEL_DOWNLOAD_PATH
    caminho.parent.mkdir(parents=True, exist_ok=True)
    temporario = caminho.with_name(f"{caminho.name}.{os.getpid()}.tmp")

    try:
        with urlopen(url, timeout=60) as resposta:  # noqa: S310, RUF100
            conteudo = cast("bytes", resposta.read())
        _ = temporario.write_bytes(conteudo)
        _ = temporario.replace(caminho)
    except HTTPError as erro:
        raise RuntimeError(
            f"Não foi possível obter o modelo: o download falhou com HTTP {erro.code}"
        ) from erro
    except URLError as erro:
        raise RuntimeError(
            f"Não foi possível obter o modelo: falha ao baixar {url}: {erro.reason}"
        ) from erro
    finally:
        temporario.unlink(missing_ok=True)

    return caminho


# A extensão só sabe ler um caminho: ela chama esta função antes de carregar o
# separador padrão, e o arquivo passa a existir na primeira chamada.
_ = _extensao._registrar_garantia_de_modelo(obter_modelo)
