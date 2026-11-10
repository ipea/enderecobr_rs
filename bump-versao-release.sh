#!/usr/bin/env bash
set -euo pipefail

# Checagem se o argumento existe
DRY_RUN=0
VERSION=""

for arg in "$@"; do
  case "$arg" in
    -n | --dry-run) DRY_RUN=1 ;;
    -h | --help)
      echo "Uso: $0 [-n|--dry-run] <versão>" >&2
      exit 0
      ;;
    -*)
      echo "Erro: opção desconhecida: $arg" >&2
      exit 1
      ;;
    *)
      if [[ -n "$VERSION" ]]; then
        echo "Erro: argumento demais: $arg" >&2
        exit 1
      fi
      VERSION="$arg"
      ;;
  esac
done

if [[ -z "$VERSION" ]]; then
  echo "Uso: $0 [-n|--dry-run] <versão>" >&2
  exit 1
fi

# Verificação do formato do argumento como versionamento semântico
if [[ ! "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "Erro: versão inválida: $VERSION" >&2
  echo "Esperado: MAJOR.MINOR.PATCH (ex.: 0.4.3)" >&2
  exit 1
fi

if git rev-parse -q --verify "refs/tags/v$VERSION" >/dev/null; then
  echo "Erro: tag v$VERSION já existe. Remova com git tag -d v$VERSION" >&2
  exit 1
fi

if [[ "$DRY_RUN" -eq 1 ]]; then
  echo "[dry-run] versões atuais:"
  grep -H -m1 -E '^version = ' Cargo.toml bindings/python/pyproject.toml bindings/python/Cargo.toml | sed 's/^/  /'
  echo "[dry-run] passariam a: $VERSION"
  echo "[dry-run] rodaria: cargo check (x2), uv sync, git commit, git tag v$VERSION"
  echo "[dry-run] nada foi alterado"
  exit 0
fi

# Substituições inplace das versões nos arquivos chave
# Considera só a primeira ocorrencia do "version = " nos arquivos
sed -i -E "0,/^version = .*/s/^version = \".*\"/version = \"$VERSION\"/" Cargo.toml
sed -i -E "0,/^version = .*/s/^version = \".*\"/version = \"$VERSION\"/" bindings/python/pyproject.toml
sed -i -E "0,/^version = .*/s/^version = \".*\"/version = \"$VERSION\"/" bindings/python/Cargo.toml

# Faz o bump de versão nos arquivos de lock
cargo check
cargo check --manifest-path bindings/python/Cargo.toml
uv sync --directory bindings/python

# Faz o git commit desses caras todos (.toml e .lock)
git add Cargo.toml Cargo.lock bindings/python/pyproject.toml bindings/python/Cargo.toml bindings/python/Cargo.lock bindings/python/Cargo.toml bindings/python/uv.lock
git commit -m "chore: release v$VERSION"

# Cria a tag para a release
git tag "v$VERSION"

cat <<EOF

Versão $VERSION commitada e tagueada localmente.

Para terminar de subir:
  git push origin HEAD
  git push origin "v$VERSION"

O push da tag dispara: publish-cargo (crates.io), maturin (PyPI), GH Release,
atualizar-snapshot e trigger-readthedocs.

Depois confira:
  gh release view "v$VERSION"   # release criada pelo workflow
  gh run list --limit 6         # resultado de cada workflow
EOF
