.PHONY: test popular etiquetar treinar tunar avaliar validar estressar segmentar explicar exemplos diferencial geocode otimizar instalar

DIR_DADOS = ./data
N ?= 5000
K ?= 3
EXEMPLOS ?= 100
MODELO ?=
ADDR ?= RUA DAS FLORES 123 APTO 45 - CENTRO

-include .env
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

validar:
	uv run crf avaliar --kfold $(K)

estressar: treinar
	uv run crf avaliar --estresse

segmentar:
	uv run crf segmentar

explicar:
	uv run crf explicar "$(ADDR)"

exemplos:
	uv run crf visualizar --abrir --alvo $(EXEMPLOS) $(if $(MODELO),--modelo $(MODELO))

diferencial:
	uv run crf diferencial

geocode:
	uv run crf geocode comparar $(BASE) --estado $(ESTADO) --municipio $(MUNICIPIO)

otimizar:
	uv run python scripts/otimizar_politica.py --n $(N)

test:
	uv run pytest
