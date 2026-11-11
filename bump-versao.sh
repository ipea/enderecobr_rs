#!/usr/bin/env bash
set -euo pipefail

# Sobe uma versão da biblioteca e, opcionalmente, um modelo CRF novo: roda os
# testes de integração com o modelo, publica o arquivo como asset de uma release
# do GitHub, aponta as constantes e as versões para ele e fecha tudo num único
# commit tagueado. Uso:
#   ./bump-versao.sh [-n|--dry-run] <versão>
#   ./bump-versao.sh [-n|--dry-run] <versão> <versão do modelo> <caminho do modelo>
#   ./bump-versao.sh 0.6.0 0.3.0 ~/modelos/tagger_novo.crf

DRY_RUN=0
VERSAO=""
VERSAO_MODELO=""
MODELO=""

for arg in "$@"; do
  case "$arg" in
  -n | --dry-run) DRY_RUN=1 ;;
  -h | --help)
    sed -n '3,9p' "$0" | sed 's/^# \{0,1\}//'
    exit 0
    ;;
  -*)
    echo "Erro: opção desconhecida: $arg" >&2
    exit 1
    ;;
  *)
    if [[ -z "$VERSAO" ]]; then
      VERSAO="${arg#v}"
    elif [[ -z "$VERSAO_MODELO" ]]; then
      VERSAO_MODELO="${arg#v}"
    elif [[ -z "$MODELO" ]]; then
      MODELO="$arg"
    else
      echo "Erro: argumento demais: $arg" >&2
      exit 1
    fi
    ;;
  esac
done

if [[ -z "$VERSAO" ]]; then
  echo "Uso: $0 [-n|--dry-run] <versão> [<versão do modelo> <caminho do modelo>]" >&2
  echo "Exemplo: $0 0.6.0 0.3.0 ~/modelos/tagger_novo.crf" >&2
  exit 1
fi

if [[ -n "$VERSAO_MODELO" && -z "$MODELO" ]] || [[ -z "$VERSAO_MODELO" && -n "$MODELO" ]]; then
  echo "Erro: informe a versão do modelo e o caminho do modelo, ou nenhum dos dois" >&2
  exit 1
fi

SEMVER='^[0-9]+\.[0-9]+\.[0-9]+$'
if [[ ! "$VERSAO" =~ $SEMVER ]]; then
  echo "Erro: versão inválida: $VERSAO" >&2
  echo "Esperado: MAJOR.MINOR.PATCH (ex.: 0.6.0)" >&2
  exit 1
fi

if [[ -n "$VERSAO_MODELO" && ! "$VERSAO_MODELO" =~ $SEMVER ]]; then
  echo "Erro: versão de modelo inválida: $VERSAO_MODELO" >&2
  echo "Esperado: MAJOR.MINOR.PATCH (ex.: 0.3.0)" >&2
  exit 1
fi

if git rev-parse -q --verify "refs/tags/v$VERSAO" >/dev/null; then
  echo "Erro: tag v$VERSAO já existe. Remova com git tag -d v$VERSAO" >&2
  exit 1
fi

TAG_MODELO=""
ARQUIVO_CONSTANTES="src/separador_endereco/modelo.rs"
URL_MODELO=""
if [[ -n "$VERSAO_MODELO" ]]; then
  TAG_MODELO="modelo-crf-v$VERSAO_MODELO"
  URL_MODELO="https://github.com/ipea/enderecobr_rs/releases/download/$TAG_MODELO/tagger.crf"

  if [[ ! -f "$MODELO" ]]; then
    echo "Erro: modelo não encontrado: $MODELO" >&2
    exit 1
  fi

  # Assinatura dos modelos do crfsuite.
  if [[ "$(head -c 4 "$MODELO")" != "lCRF" ]]; then
    echo "Erro: $MODELO não parece um modelo do crfsuite" >&2
    exit 1
  fi

  if gh release view "$TAG_MODELO" >/dev/null 2>&1; then
    echo "Erro: release $TAG_MODELO já existe" >&2
    exit 1
  fi
fi

# Sanidade: os casos de sanidade e a paridade de rótulos vivem nos testes de
# integração do Rust (`tests/crf.rs`), para não haver duas listas de casos. A
# variável abaixo transforma "modelo ausente" em falha, senão os testes pulariam
# e um modelo quebrado passaria.
if [[ -n "$TAG_MODELO" ]]; then
  echo "Rodando os testes de sanidade com $MODELO"
  ENDERECOBR_MODELO="$MODELO" ENDERECOBR_MODELO_SEM_DOWNLOAD=1 TESTE_CRF_EXIGE_MODELO=1 \
    cargo test --quiet --test crf
  echo "Sanidade ok: testes de integração aprovados"
fi

SUFIXO_MODELO=""
if [[ -n "$TAG_MODELO" ]]; then
  SUFIXO_MODELO=" (modelo $TAG_MODELO)"
fi

if [[ "$DRY_RUN" -eq 1 ]]; then
  echo
  echo "[dry-run] em Cargo.toml, bindings/python/pyproject.toml e bindings/python/Cargo.toml:"
  echo "  version -> $VERSAO"
  echo "[dry-run] em README.md:"
  echo "  exemplo de instalação -> enderecobr_rs = { version = \"$VERSAO\" }"
  if [[ -n "$TAG_MODELO" ]]; then
    echo "[dry-run] em $ARQUIVO_CONSTANTES:"
    echo "  MODEL_DOWNLOAD_PATH -> .../download/$TAG_MODELO/tagger.crf"
    echo "  VERSAO_MODELO       -> $TAG_MODELO"
    echo "[dry-run] gh release create $TAG_MODELO <tagger.crf> --title $TAG_MODELO"
  fi
  echo "[dry-run] commit: chore: release v$VERSAO$SUFIXO_MODELO"
  echo "[dry-run] tag: v$VERSAO"
  echo "[dry-run] nada foi alterado"
  exit 0
fi

# Aponta as constantes do modelo para a versão nova. O sed escreve num
# temporário e o resultado é conferido antes de substituir o original: uma
# substituição errada não pode chegar ao arquivo (o `&` de `&str` é especial no
# replacement do sed e precisa sair escapado como `\&`).
atualizar_constantes() {
  local tag="$1" temporario
  temporario="$(mktemp)"

  sed -E \
    -e "s#(releases/download/)[^/\"]+(/tagger\.crf)#\1$tag\2#" \
    -e "s#^pub const VERSAO_MODELO: &str = \"[^\"]*\";#pub const VERSAO_MODELO: \\&str = \"$tag\";#" \
    "$ARQUIVO_CONSTANTES" >"$temporario"

  local url_ok versao_ok duplicado=0
  url_ok="$(grep -c "download/$tag/tagger.crf" "$temporario" || true)"
  versao_ok="$(grep -c "^pub const VERSAO_MODELO: &str = \"$tag\";$" "$temporario" || true)"
  if grep -q '^pub const .*pub const ' "$temporario"; then
    duplicado=1
  fi

  if [[ "$url_ok" -ne 1 || "$versao_ok" -ne 1 || "$duplicado" -ne 0 ]]; then
    echo "Erro: substituição das constantes saiu errada; $ARQUIVO_CONSTANTES não foi alterado" >&2
    diff -u "$ARQUIVO_CONSTANTES" "$temporario" >&2 || true
    rm -f "$temporario"
    exit 1
  fi

  mv "$temporario" "$ARQUIVO_CONSTANTES"
}

# README: o exemplo de instalação repete a última versão publicada. Mesmo
# cuidado do anterior: só substitui se o resultado esperado for único.
atualizar_readme() {
  local temporario
  temporario="$(mktemp)"

  sed -E "s#^(enderecobr_rs = \{ version = )\"[^\"]*\"#\1\"$VERSAO\"#" README.md >"$temporario"

  if [[ "$(grep -c "^enderecobr_rs = { version = \"$VERSAO\" }$" "$temporario" || true)" -ne 1 ]]; then
    echo "Erro: exemplo de instalação do README saiu errado; README.md não foi alterado" >&2
    diff -u README.md "$temporario" >&2 || true
    rm -f "$temporario"
    exit 1
  fi

  mv "$temporario" README.md
}

# O asset sobe primeiro: se a release falhar, o repositório continua apontando
# para um modelo que existe.
if [[ -n "$TAG_MODELO" ]]; then
  TMP="$(mktemp -d)"
  trap 'rm -rf "$TMP"' EXIT
  cp "$MODELO" "$TMP/tagger.crf"
  gh release create "$TAG_MODELO" "$TMP/tagger.crf" \
    --title "$TAG_MODELO" \
    --notes "Modelo CRF $TAG_MODELO."

  if ! curl -sfIL "$URL_MODELO" >/dev/null; then
    echo "Erro: asset não acessível em $URL_MODELO" >&2
    exit 1
  fi

  atualizar_constantes "$TAG_MODELO"
fi

# Substituições inplace das versões nos arquivos chave
# Considera só a primeira ocorrencia do "version = " nos arquivos
sed -i -E "0,/^version = .*/s/^version = \".*\"/version = \"$VERSAO\"/" Cargo.toml
sed -i -E "0,/^version = .*/s/^version = \".*\"/version = \"$VERSAO\"/" bindings/python/pyproject.toml
sed -i -E "0,/^version = .*/s/^version = \".*\"/version = \"$VERSAO\"/" bindings/python/Cargo.toml

atualizar_readme

# Faz o bump de versão nos arquivos de lock
cargo check
cargo check --manifest-path bindings/python/Cargo.toml
uv sync --directory bindings/python

# Commit único: versões, locks e, quando houver, o modelo novo.
ARQUIVOS=(
  Cargo.toml Cargo.lock README.md
  bindings/python/pyproject.toml bindings/python/Cargo.toml
  bindings/python/Cargo.lock bindings/python/uv.lock
)
if [[ -n "$TAG_MODELO" ]]; then
  ARQUIVOS+=("$ARQUIVO_CONSTANTES")
fi
git add "${ARQUIVOS[@]}"

git commit -m "chore: release v$VERSAO$SUFIXO_MODELO"

# Cria a tag para a release
git tag "v$VERSAO"

LINHA_MODELO=""
if [[ -n "$TAG_MODELO" ]]; then
  LINHA_MODELO="Modelo publicado em $URL_MODELO"
fi

cat <<EOF

Versão $VERSAO commitada e tagueada localmente.
$LINHA_MODELO

Para terminar de subir:
  git push origin HEAD
  git push origin "v$VERSAO"

O push da tag dispara: publish-cargo (crates.io), maturin (PyPI), GH Release,
atualizar-snapshot e trigger-readthedocs.

Depois confira:
  gh release view "v$VERSAO"   # release criada pelo workflow
  gh run list --limit 6        # resultado de cada workflow

Para reverter, antes do push:
  git reset HEAD^
  git tag -d "v$VERSAO"
EOF
