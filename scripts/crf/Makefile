.PHONY: test popular etiquetar treinar tunar avaliar segmentar diferencial geocode instalar

DIR_DADOS = ./data

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

geocode:
	uv run crf geocode comparar $(BASE) --estado $(ESTADO) --municipio $(MUNICIPIO)

test:
	uv run pytest
