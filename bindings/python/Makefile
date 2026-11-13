.PHONY: build sync doc test

build:
	uv run maturin develop

sync:
	uv sync

doc:
	uv run --extra doc mkdocs serve -f ../../mkdocs.yml

test:
	uv run pytest --cov

