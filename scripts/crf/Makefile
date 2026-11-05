.PHONY: test popular etiquetar treinar tunar avaliar segmentar explicar diferencial geocode otimizar instalar

DIR_DADOS = ./data
N ?= 5000
ADDR ?= RUA DAS FLORES 123 APTO 45 - CENTRO

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

explicar:
	uv run crf explicar "$(ADDR)"

diferencial:
	uv run crf diferencial

geocode:
	uv run crf geocode comparar $(BASE) --estado $(ESTADO) --municipio $(MUNICIPIO)

otimizar:
	uv run python scripts/otimizar_politica.py --n $(N)

test:
	uv run pytest
