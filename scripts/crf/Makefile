.PHONY: test popular etiquetar treinar tunar avaliar segmentar diferencial comparar-geocode

DIR_DADOS = ./data
DIR_SQLS = ./sql

include .env
export

### Pipeline

popular:
	uv run crf popular $(TIPO) $(BASE) $(DIR_DADOS)/anotado/dataset.sqlite

etiquetar:
	uv run crf etiquetar lote $(DIR_DADOS)/anotado/dataset.sqlite

treinar:
	uv run crf treinar

tunar:
	uv run crf tunar

avaliar: treinar
	uv run crf avaliar

segmentar:
	uv run crf segmentar

diferencial:
	uv run crf diferencial

comparar-geocode:
	uv run crf comparar-geocode $(BASE)

test:
	uv run pytest

