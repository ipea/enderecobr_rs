## Fluxo de uso

> PS: Comandos no Makefile também.

```bash
uv sync # Sincronizar as dependências uv -> venv
uv run maturin develop # Compilar projeto
uv run pytest --cov # Rodar testes
uv run --extra doc mkdocs serve -f ../../mkdocs.yml # Opcional: avaliar documentação.
```
