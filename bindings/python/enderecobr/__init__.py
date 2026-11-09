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

from enderecobr.enderecobr import *
