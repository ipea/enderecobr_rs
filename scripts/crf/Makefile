.PHONY: test avaliacao-manual eval treinar

DIR_DADOS = ./dados
DIR_BRUTOS = ./dados/brutos
DIR_INTERMEDIARIOS = ./dados/intermediarios
DIR_SQLS = ./src/sql
DIR_PYTHON = ./src/crf_endereco

include .env
export

### Utilitários

test:
	uv run pytest

avaliacao-manual:
	uv run src/crf_endereco/teste_manual.py

# Preferi não colocar o script de treinamento aqui para não precisar executar toda ver que uma virgula nele mudar. Além de que teria que colocar todas as dependências do projeto aqui para ser justo.
treinar:
	uv run $(DIR_PYTHON)/treinamento.py

etiquetar:
	uv run $(DIR_PYTHON)/etiquetar.py


### Dataset final

$(DIR_DADOS)/treino.parquet $(DIR_DADOS)/teste.parquet: $(DIR_SQLS)/dataset_final.sql $(DIR_INTERMEDIARIOS)/cneas.parquet $(DIR_INTERMEDIARIOS)/cno.parquet $(DIR_INTERMEDIARIOS)/cnes.parquet $(DIR_INTERMEDIARIOS)/censo_escolar.parquet $(DIR_INTERMEDIARIOS)/postos_cadunico.parquet $(DIR_INTERMEDIARIOS)/cnefe.parquet $(DIR_INTERMEDIARIOS)/cnpj.parquet
	duckdb < $<

eval: $(DIR_DADOS)/teste.parquet $(DIR_PYTHON)/eval.py $(DIR_DADOS)/tagger.crf
	uv run $(DIR_PYTHON)/eval.py

