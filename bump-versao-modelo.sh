#!/usr/bin/env bash
set -euo pipefail

# Publica um novo modelo CRF: roda testes de sanidade, sobe o arquivo como
# asset de uma release do GitHub e aponta o código para ele. Uso:
#   ./bump-versao-modelo.sh [-n|--dry-run] <versão> <caminho do modelo>
#   ./bump-versao-modelo.sh 0.3.0 ~/modelos/tagger_novo.crf

DRY_RUN=0
VERSAO=""
MODELO=""

for arg in "$@"; do
  case "$arg" in
  -n | --dry-run) DRY_RUN=1 ;;
  -h | --help)
    sed -n '3,6p' "$0" | sed 's/^# \{0,1\}//'
    exit 0
    ;;
  -*)
    echo "Erro: opção desconhecida: $arg" >&2
    exit 1
    ;;
  *)
    if [[ -z "$VERSAO" ]]; then
      VERSAO="${arg#v}"
    elif [[ -z "$MODELO" ]]; then
      MODELO="$arg"
    else
      echo "Erro: argumento demais: $arg" >&2
      exit 1
    fi
    ;;
  esac
done

if [[ -z "$VERSAO" || -z "$MODELO" ]]; then
  echo "Uso: $0 [-n|--dry-run] <versão> <caminho do modelo>" >&2
  echo "Exemplo: $0 0.3.0 ~/modelos/tagger_novo.crf" >&2
  exit 1
fi

TAG="modelo-crf-v$VERSAO"
ARQUIVO_CONSTANTES="src/separador_endereco/modelo.rs"
URL="https://github.com/ipea/enderecobr_rs/releases/download/$TAG/tagger.crf"

if [[ ! "$VERSAO" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "Erro: versão inválida: $VERSAO" >&2
  echo "Esperado: MAJOR.MINOR.PATCH (ex.: 0.3.0)" >&2
  exit 1
fi

if [[ ! -f "$MODELO" ]]; then
  echo "Erro: modelo não encontrado: $MODELO" >&2
  exit 1
fi

# Assinatura dos modelos do crfsuite.
if [[ "$(head -c 4 "$MODELO")" != "lCRF" ]]; then
  echo "Erro: $MODELO não parece um modelo do crfsuite" >&2
  exit 1
fi

if gh release view "$TAG" >/dev/null 2>&1; then
  echo "Erro: release $TAG já existe" >&2
  exit 1
fi

# Casos de sanidade: invariantes que o modelo novo não pode quebrar.
# Formato: "endereço|trecho esperado na saída estruturada".
CASOS=(
  "rua das flores 123, centro, sao paulo, sp, 01000-000|\"cep\":\"01000-000\""
  "rua das flores 123, centro, sao paulo, sp, 13000-000|\"cep\":\"13000-000\""
  "rua sete de setembro 33, centro, porto alegre, rs, 90010-190|\"cep\":\"90010-190\""
  "travessa sao jose 15 loja 3, centro, niteroi, rj, 24020-000|\"cep\":\"24020-000\""
  "r a, n. 1, ap 2|\"numero\":\"1\""
  "av atlantica, 123, apto 301|\"complemento\":\"APARTAMENTO 301\""
  "rua brasil, 123|\"logradouro\":\"RUA BRASIL\""
  "av paulista 1578, bela vista, sao paulo, sp|\"localidade\":\"BELA VISTA\""
)

echo "Rodando ${#CASOS[@]} casos de sanidade com $MODELO"
falhas=0
for caso in "${CASOS[@]}"; do
  entrada="${caso%%|*}"
  esperado="${caso#*|}"
  saida="$(ENDERECOBR_MODELO="$MODELO" ENDERECOBR_MODELO_SEM_DOWNLOAD=1 \
    cargo run --quiet --release --features cli --bin padronizar -- estruturacao <<<"$entrada")"
  if [[ "$saida" != *"$esperado"* ]]; then
    echo "  FALHOU: $entrada" >&2
    echo "    esperado conter: $esperado" >&2
    echo "    obtido:          $saida" >&2
    falhas=$((falhas + 1))
  fi
done

if [[ "$falhas" -gt 0 ]]; then
  echo "Erro: modelo reprovado em $falhas de ${#CASOS[@]} casos de sanidade" >&2
  exit 1
fi
echo "Sanidade ok: ${#CASOS[@]} casos aprovados"

if [[ "$DRY_RUN" -eq 1 ]]; then
  echo
  echo "[dry-run] em $ARQUIVO_CONSTANTES:"
  echo "  MODEL_DOWNLOAD_PATH -> .../download/$TAG/tagger.crf"
  echo "  VERSAO_MODELO       -> $TAG"
  echo "[dry-run] commit: chore: bump $TAG"
  echo "[dry-run] gh release create $TAG <tagger.crf> --title $TAG"
  echo "[dry-run] nada foi alterado"
  exit 0
fi

# Aponta as constantes para o novo modelo.
sed -i -E "s#(releases/download/)[^/\"]+(/tagger\.crf)#\1$TAG\2#" "$ARQUIVO_CONSTANTES"
sed -i -E "s#^pub const VERSAO_MODELO: &str = \"[^\"]*\";#pub const VERSAO_MODELO: &str = \"$TAG\";#" "$ARQUIVO_CONSTANTES"

git add "$ARQUIVO_CONSTANTES"
git commit -m "chore: bump $TAG"

# Sobe o modelo como asset da release (o asset precisa se chamar tagger.crf).
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
cp "$MODELO" "$TMP/tagger.crf"
gh release create "$TAG" "$TMP/tagger.crf" \
  --title "$TAG" \
  --notes "Modelo CRF $TAG."

if ! curl -sfIL "$URL" >/dev/null; then
  echo "Erro: asset não acessível em $URL" >&2
  exit 1
fi

cat <<EOF

Modelo publicado em $URL

Para terminar de subir:
  git push origin HEAD

Depois confira:
  gh release view $TAG          # asset tagger.crf presente
  gh run list --limit 5         # CI do commit do bump

Se quiser que este modelo passe a ser o padrão das próximas versões da
biblioteca, rode também o ./bump-versao-release.sh.
EOF
