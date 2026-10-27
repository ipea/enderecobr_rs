# CRF de endereços

Segmentador de endereços brasileiros: o CRF treinado aqui é o que o
`enderecobr_rs` embarca, e as duas implementações (Python e Rust) compartilham o
mesmo modelo e as mesmas features.

## Pipeline

```
data/brutos/*            bases públicas (CNEFE, CNEAS, CNES, Censo Escolar, ...)
        │  crf popular        (+ .sql em sql/)
        ▼
data/anotado/dataset.sqlite   um endereço bruto por linha
        │  crf etiquetar      (LLM com tool-calling: CNEFE, busca web, fetch)
        ▼
data/modelos/tagger.crf       ── crf treinar ── crf avaliar / crf inspecionar
        │
        ├── crf segmentar          endereço avulso pelo stdin
        ├── crf diferencial        Python vs binário Rust (mesmo modelo)
        └── crf comparar-geocode   geocode com o endereço bruto vs segmentado
```

## Comandos

Tudo passa por um único binário:

```bash
crf popular imoveis_uniao data/brutos/imoveis.xlsx data/anotado/dataset.sqlite -n 1000
crf etiquetar lote data/anotado/dataset.sqlite --uf RJ --origem siase
crf treinar
crf avaliar
crf segmentar
crf diferencial
crf comparar-geocode data/brutos/rais_test/
```

`make` expõe os mesmos comandos (`make test`, `make etiquetar`, ...).

## Estrutura

| caminho | papel |
|---|---|
| `src/crf_endereco/config.py` | todos os caminhos (dados, tagger, saídas) |
| `src/crf_endereco/features/` | normalização, tokenização e features do CRF |
| `src/crf_endereco/rotulos.py` | segmentos verbatim → rótulos BIO |
| `src/crf_endereco/modelos/` | treino, tuning, avaliação, inferência |
| `src/crf_endereco/anotacao/` | anotação por LLM (`populacao/` traz uma base por arquivo) |
| `src/crf_endereco/anotacao/estratificacao.py` | peso 1/(anotados+1) e alocação entre estratos (puro) |
| `src/crf_endereco/anotacao/consultas.py` | SQL de pendentes e estratos |
| `src/crf_endereco/anotacao/amostragem.py` | coleta do lote balanceado UF → origem |
| `src/crf_endereco/geocode/` | comparação bruto vs segmentado |
| `src/crf_endereco/segmentador_rust.py` | único adaptador do binário do `enderecobr_rs` |
| `src/crf_endereco/cli/` | só a cola do typer |
| `sql/` | consultas DuckDB que montam as bases |

Nada fora de `config.py` monta caminho: `CRF_DATA_DIR` (padrão `./data`) e
`CNEFE_PATH` sobrescrevem os padrões. `data/` é ignorado pelo git.

## Configuração

`.env` na raiz de `scripts/crf`:

```
API_URL=...
API_KEY=...
API_MODEL=...
SEARX_URL=...          # opcional: sem ela a busca web fica indisponível
```

O prompt e a ontologia de rótulos ficam em
`src/crf_endereco/anotacao/prompt_sistema.md`.

## Bases candidatas

- https://dados.gov.br/dados/conjuntos-dados/postos-de-cadastramento-do-cadastro-unico - lat long, separado
- https://dados.gov.br/dados/conjuntos-dados/cnes-cadastro-nacional-de-estabelecimentos-de-saude - lat long, separado
- https://dados.gov.br/dados/conjuntos-dados/inep-microdados-do-censo-escolar-da-educacao-basica - separado, sem lat long, pode dar join com o de baixo
- https://www.gov.br/inep/pt-br/acesso-a-informacao/dados-abertos/inep-data/catalogo-de-escolas - endereco junto, lat long
- https://dados.gov.br/dados/conjuntos-dados/cneas--cadastro-nacional-de-entidades-de-assistencia-social - endereco separado, sem lat long
- https://dados.gov.br/dados/conjuntos-dados/cadastro-nacional-de-obras-cno - endereço separado, sem lat long
- https://dados.gov.br/dados/conjuntos-dados/censo-suas - poucos dados, lat long, referencia
- https://dados.gov.br/dados/conjuntos-dados/cadastro-de-imoveis-rurais---cafir - algumas partes do endereco juntas, sem lat long
- https://qlik-publico.paineis.gov.br/extensions/transparencia-ativa/transparencia-ativa.html - lat long, tudo junto
- https://dados.gov.br/dados/conjuntos-dados/sistema-de-transportes-de-servidores-publicos---taxigov-v2 - lat log, tudo junto
- https://www.gov.br/funai/pt-br/atuacao/terras-indigenas/geoprocessamento-e-mapas - lat long, só o nome da aldeia
- https://dados.gov.br/dados/conjuntos-dados/fiscalizacao-auto-de-infracao - lat long, tudo junto, as vezes tem endereço de referencia
