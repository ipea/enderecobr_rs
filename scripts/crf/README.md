# CRF de endereços

Segmentador de endereços brasileiros: o CRF treinado aqui é o que o
`enderecobr_rs` embarca, e as duas implementações (Python e Rust) compartilham o
mesmo modelo e as mesmas features.

## Pipeline

```text
data/brutos/*                 bases públicas (Imóveis da União, CNEAS, CadÚnico,
        │  crf popular         ANEEL, CAFIR, Censo Escolar, SIASE)
        ▼
data/anotado/dataset.sqlite   um endereço bruto por linha
        │  crf etiquetar      (LLM com tool-calling: CNEFE, busca web, fetch)
        ▼
data/modelos/tagger.crf       ── crf treinar ── crf avaliar / crf inspecionar
        │
        ├── crf segmentar          endereço avulso pelo stdin
        ├── crf diferencial        Python vs binário Rust (mesmo modelo)
        └── crf geocode comparar   geocode com o endereço bruto vs segmentado
```

## Comandos

```bash
crf popular imoveis_uniao data/brutos/imoveis.xlsx data/anotado/dataset.sqlite -n 1000
crf etiquetar avulso "RUA DAS FLORES 123 AP 45"
crf etiquetar lote data/anotado/dataset.sqlite --uf RJ --origem siase -l 500
crf treinar
crf avaliar
crf segmentar
crf diferencial
crf geocode comparar data/brutos/rais_test/ --estado uf --municipio municipio
```

`make` expõe os mesmos comandos (`make test`, `make etiquetar`, ...).

## Como o lote é sorteado

`crf etiquetar lote` não pega "os N primeiros": `pendentes()` sorteia com
`row_number() OVER (PARTITION BY uf, origem ORDER BY random())` e ordena por essa
rodada, o que intercala as células (UF, origem) — a primeira linha de cada célula
vem antes da segunda de qualquer uma. Dentro da rodada, a célula com menos
anotações vem primeiro, o que empurra o lote para o que ainda não foi coberto.
Tudo em uma consulta (`anotacao/pendentes.py`).

## Estrutura

| caminho | papel |
|---|---|
| `config.py` | caminhos (dados, tagger) e `Config` do ambiente (LLM) |
| `registro.py` | o registro a etiquetar e a normalização dos campos das bases |
| `dataset.py` | único acesso ao SQLite anotado (gravar, ler, exemplos do modelo) |
| `ui.py` | console e barra de progresso |
| `features/` | normalização, tokenização e features do CRF (paridade com o Rust) |
| `rotulos.py` | segmentos verbatim → rótulos BIO |
| `modelo/crf.py` | dados de treino, treino, tuning, tagger e inferência |
| `modelo/relatorio.py` | métricas e relatório de avaliação |
| `anotacao/agente.py` | prompt, loop reAct e validação da resposta da LLM |
| `anotacao/ferramentas.py` | tools expostas à LLM (CNEFE, busca web, fetch) |
| `anotacao/cliente_http.py` | HTTP com retry e backoff |
| `anotacao/pendentes.py` | recorte e sorteio do lote |
| `anotacao/filtro_crf.py` | filtro por tipos que o CRF prevê (`--apenas-tipos`) |
| `anotacao/lote.py` | execução em paralelo e gravação do lote |
| `anotacao/populacao/` | uma base pública por arquivo (`Fonte` = SQL + mapeamento) |
| `geocode/comparacao.py` | comparação bruto vs segmentado (relatórios) |
| `segmentador_rust.py` | único adaptador do binário do `enderecobr_rs` |
| `cli/` | cola do typer: `producao`, `modelo`, `geocode` |

Nada fora de `config.py` monta caminho: `CRF_DATA_DIR` (padrão `./data`),
`CNEFE_PATH` e `MUNICIPIOS_PATH` sobrescrevem os padrões. `data/` é ignorado
pelo git.

## Configuração

`.env` na raiz de `scripts/crf`:

```
API_URL=...
API_KEY=...
API_MODEL=...
SEARX_URL=...          # opcional: sem ela a busca web fica indisponível
API_TOOLS_STRICT=1     # opcional: manda `strict: true` no schema das tools
TIMEOUT_SQL=15         # opcional: teto de segundos por query da LLM
```

O prompt e a ontologia de rótulos ficam em
`src/crf_endereco/anotacao/prompt_sistema.md` e `anotacao/ontologia.py`.

## Bases candidatas

- <https://dados.gov.br/dados/conjuntos-dados/postos-de-cadastramento-do-cadastro-unico> - lat long, separado
- <https://dados.gov.br/dados/conjuntos-dados/cnes-cadastro-nacional-de-estabelecimentos-de-saude> - lat long, separado
- <https://dados.gov.br/dados/conjuntos-dados/inep-microdados-do-censo-escolar-da-educacao-basica> - separado, sem lat long, pode dar join com o de baixo
- <https://www.gov.br/inep/pt-br/acesso-a-informacao/dados-abertos/inep-data/catalogo-de-escolas> - endereco junto, lat long
- <https://dados.gov.br/dados/conjuntos-dados/cneas--cadastro-nacional-de-entidades-de-assistencia-social> - endereco separado, sem lat long
- <https://dados.gov.br/dados/conjuntos-dados/cadastro-nacional-de-obras-cno> - endereço separado, sem lat long
- <https://dados.gov.br/dados/conjuntos-dados/censo-suas> - poucos dados, lat long, referencia
- <https://dados.gov.br/dados/conjuntos-dados/cadastro-de-imoveis-rurais---cafir> - algumas partes do endereco juntas, sem lat long
- <https://qlik-publico.paineis.gov.br/extensions/transparencia-ativa/transparencia-ativa.html> - lat long, tudo junto
- <https://dados.gov.br/dados/conjuntos-dados/sistema-de-transportes-de-servidores-publicos---taxigov-v2> - lat log, tudo junto
- <https://www.gov.br/funai/pt-br/atuacao/terras-indigenas/geoprocessamento-e-mapas> - lat long, só o nome da aldeia
- <https://dados.gov.br/dados/conjuntos-dados/fiscalizacao-auto-de-infracao> - lat long, tudo junto, as vezes tem endereço de referencia
