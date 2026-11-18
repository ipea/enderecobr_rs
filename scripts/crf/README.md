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
        ├── crf explicar           dissec a segmentação de um endereço, etapa por etiqueta
        ├── crf diferencial        Python vs binário Rust (mesmo modelo)
        └── crf geocode comparar   geocode com o endereço bruto vs segmentado
```

## Comandos

```bash
crf popular imoveis_uniao data/brutos/imoveis.xlsx data/anotado/dataset.sqlite -n 1000
crf etiquetar avulso "RUA DAS FLORES 123 AP 45"
crf etiquetar lote data/anotado/dataset.sqlite --uf RJ --origem siase -l 500
crf etiquetar lote data/anotado/dataset.sqlite --busca "asa norte" --incertos-media 0.8
crf etiquetar lote data/anotado/dataset.sqlite --incertos 0.4,0.7 -l 200   # faixa de confiança
crf etiquetar lote data/anotado/dataset.sqlite --divergentes --modelo data/modelos/tagger_v13.crf
crf etiquetar lote data/anotado/dataset.sqlite -l 500 -b 5 -c 4   # 5 por conversa, 4 em paralelo
crf explorar data/anotado/dataset.sqlite -l 20                     # os casos mais difíceis
crf explorar data/anotado/dataset.sqlite --divergentes -l 3 --detalhar
crf explorar data/anotado/dataset.sqlite --revisados -l 10 --busca "quadra 4"
crf treinar
crf avaliar
crf avaliar --estresse
crf avaliar --kfold 3        # validação cruzada: retreina 3 modelos, ignora o tagger
crf segmentar
crf explicar "RUA DAS FLORES 123 APTO 45 - CENTRO"
crf visualizar --alvo 100                     # página HTML com exemplos reais
crf visualizar --modelo data/modelos/tagger_v15.crf --alvo 100
crf diferencial
crf geocode comparar data/brutos/rais_test/ --estado uf --municipio municipio
crf geocode comparar data/anotado/dataset.sqlite --estado uf --municipio municipio \
    --endereco endereco --modelo data/modelos/tagger_v6.crf
```

`crf geocode comparar` aceita parquet (arquivo, diretório ou glob) ou o dataset
em sqlite (tabela `enderecos`, lida pelo scanner do DuckDB); `--modelo` aponta o
tagger usado na segmentação e entra no nome das saídas, para trocar de modelo sem
sobrescrever execuções anteriores.

## Como a avaliação sabe o que o modelo não viu

`crf treinar` grava no próprio banco, na coluna `recorte`, o papel de cada
endereço no split (`<modelo>/treino` ou `<modelo>/teste`). `crf avaliar` e
`crf avaliar --estresse` leem esse recorte em vez de recalcular o split: medir no
dataset inteiro não é acurácia de generalização, é memorização disfarçada.
Modelo sem recorte gravado (treinado antes desta coluna existir) faz a avaliação
parar com um erro pedindo retreino. Treinar de novo com o mesmo nome sobrescreve
o recorte daquele modelo.

Endpoint com alvo degenerado (resposta sem segmento, ou só com trecho que não
vira rótulo: `ruido`, `outros`, `cadastro`) fica fora do treino **e** do teste:
o alvo é todo `O`, então a linha não ensina nada e cobra um acerto que não tem
gabarito. `carregar_exemplos` descarta e imprime quantas linhas caíram.

O relatório sempre compara treino e teste. Quando o teste acerta tanto quanto o
treino (queda menor que `QUEDA_MINIMA_TOKEN`), o comando avisa que o tagger
provavelmente treinou com os endereços avaliados.

## Quando 10% de teste não mede nada

Com ~9,4 mil endereços etiquetados, o recorte de teste tem ~930 linhas, e o
erro-padrão do **endereço perfeito** ali é de ±1,5 pp: uma melhoria de 1 pp é
indistinguível de sorteio. `crf avaliar --kfold K` responde a isso do jeito
caro: treina K modelos e prevê cada endereço pelo fold que o excluiu (previsão
fora do fold, `modelo/crf.py::validacao_cruzada`). O relatório é o mesmo, sem a
coluna de treino — ali não existe um modelo único para comparar.

```bash
crf avaliar --kfold 3      # ~3 min por fold; erro-padrão do endereço perfeito ~0,5 pp
```

Ele ignora `--tagger` e o recorte gravado (o dataset inteiro entra na conta) e
usa os mesmos hiperparâmetros de `treinar`. Custa K treinos: use para decidir se
uma mudança de feature, de rótulo ou de dados vale, não no ciclo do dia a dia.

## O que o relatório mostra

`crf avaliar` e `crf treinar` imprimem o mesmo relatório (`modelo/relatorio.py`),
em blocos:

1. **Desempenho** — acerto de token, de **endereço perfeito** (todos os rótulos
   certos) e o **token certo por endereço**, treino × teste, com a queda em
   pontos percentuais. Endereço perfeito é a métrica que o uso real cobra: um
   token trocado já estraga o endereço inteiro. Token certo por endereço é a
   média, por endereço, da fração de tokens certos: um endereço de 30 tokens
   não pesa 15× mais que um de 2 (o agregado de token pesa), mas um endereço
   quase certo ainda soma.
2. **Por rótulo** — precisão, revocação, F1 e erros por etiqueta, ordenado pelo
   que mais erra.
3. **Por categoria** — o mesmo resumo por origem e por UF, ordenado pelo
   endereço perfeito, do pior para o melhor.
4. **Erros por rótulo** — heatmap real × previsto (sem a diagonal), com os
   rótulos em ordem alfabética.
5. **Tokens mais errados** — os tokens que mais aparecem mal classificados.

`--estresse` acrescenta a tabela de perturbações fixas sobre o mesmo recorte:
abreviação do tipo de via (`RUA` -> `R`), tipo em três letras, tudo em três
letras, um typo no tipo e 15% dos tokens com typo. As famílias e as sementes
ficam em `modelo/estresse.py`, e cada perturbação sorteia a partir do próprio
texto, então toda execução mede os mesmos casos; a etiqueta esperada continua
valendo porque as famílias só trocam caracteres dentro dos tokens.

`make` expõe os mesmos comandos (`make test`, `make etiquetar`, ...).

## Como o lote é filtrado

Todos os filtros recortam o mesmo conjunto e se acumulam (interseção). Os do CRF
rodam uma única passada em **todos** os pendentes já recortados por
`--busca`/`--uf`/`--origem`/... (não só em `--limite`), e só então o lote é
sorteado.

- `--busca "asa norte"` mantém os endereços que contêm o trecho (LIKE
  `'%trecho%'`, ignorando caixa e acentos; `%` e `_` são literais). Repita a
  opção para unir vários trechos em OU (`--busca "asa norte" --busca "asa sul"`),
  sem dividir por vírgula.
- `--apenas-tipos logradouro,numero` mantém quem o CRF prevê com ao menos um
  desses tipos.
- `--incertos 0.6` mantém o endereço cujo token **menos** confiável fica abaixo
  do limiar — quanto menor o limiar, mais raro (e mais grave) o caso.
- `--incertos-media 0.8` faz o mesmo pela **média** das probabilidades dos
  tokens: pega o endereço duvidoso como um todo, sem depender de um token só.
- As duas opções aceitam uma **faixa** `mínimo,máximo` (`--incertos 0.4,0.7`),
  fechada no mínimo e aberta no máximo. Serve para descartar o caso perdido
  junto com o fácil: abaixo do mínimo o endereço está corrompido além de
  conserto e acima do máximo não sobra dúvida para ensinar. Um valor só
  continua significando "abaixo de".

Os filtros de previsão compartilham o `--modelo` (padrão `data/modelos/tagger.crf`)
e as probabilidades marginais do CRF, então não precisam do binário Rust.

`crf explorar` declara **as mesmas flags** (ver "Como explorar o dataset"):
opções de recorte e de previsão vivem em `cli/filtros.py`, uma vez só.

## Como o lote reetiqueta os casos suspeitos

`--divergentes` troca a fonte do lote: em vez dos nunca-anotados, pega os
endereços do **recorte de treino** do `--modelo` (`recorte = '<modelo>/treino'`)
em que o modelo erra o rótulo com que foi treinado. Ali o exemplo já foi visto,
então errar não é falta de generalização: ou o rótulo está errado, ou o caso é
ambíguo demais — os dois merecem outra passada da LLM. O teste fica de fora de
propósito: erro lá é o preço normal de generalizar.

Antes de gastar chamada, o comando mostra quantos endereços divergem e os pares
`esperado → previsto` mais frequentes. Cada lote, ao começar, lista os seus
endereços com o que o modelo troca em cada um (rótulo abreviado em 5 caracteres,
`I_LOCALIDADE → I_LOC`), e ao terminar mostra o que a reetiquetação fez.
Medido com o recorte `tagger_v13/treino`: 870 de 8068 endereços (10,8%), com
`O ↔ LOCALIDADE`, `EMPREENDIMENTO ↔ LOCALIDADE` e `LOCALIDADE ↔ LOGRADOURO` no
topo.

O que a reetiquetação fez sai token a token, com as três etiquetas lado a lado
(só os tokens em que elas não batem) e um veredito por endereço:

```text
lote 3/174 · o que a reetiquetação mudou
  SALONIKA concorda com o CRF
  token    original     crf          agora
  SALONIKA B_LOGRADOURO B_LOCALIDADE B_LOCALIDADE
```

- **concorda com o CRF** — a LLM agora repete o que o modelo previa: o rótulo
  antigo era o problema, e o retreino deve absorver a correção.
- **rótulo mantido** — a LLM repetiu o rótulo do treino: o caso continua
  divergindo, e quem carrega o erro é o modelo (caso ambíguo ou decorado errado).
- **rótulo novo** — terceira etiqueta, nem a antiga nem a prevista: vale olhar.

- A reetiquetação **não apaga o rótulo antigo**: ele vai para
  `meta.revisoes` (`data`, `llm` e a resposta), e `meta.revisado.modelo` marca
  quem revisou. É o único registro de que a linha foi revista.
- Por isso a linha revista fica fora das próximas execuções do mesmo modelo
  (`--incluir-revisados` força de novo). Sem isso a segunda passada reetiquetaria
  exatamente as mesmas linhas, sem retreinar nada.
- A linha que falha na revisão **não é gravada**: trocar um rótulo bom por
  `{"erro": ...}` só tiraria o exemplo do treino, e a próxima execução a pega de
  novo (o erro entra na contagem do resumo).
- Compõe com os demais filtros: `--uf`, `--origem`, `--busca`, `-l`, `-b` e até
  `--incertos`/`--apenas-tipos` (que passam a recortar os divergentes).

## Como apresentar o segmentador

`crf visualizar` (`make exemplos`) gera uma página standalone
(`data/visualizacoes/exemplos.html`, abre no navegador) com endereços reais: a
faixa de tokens com o tipo previsto, a probabilidade e os pesos que a sustentam,
os segmentos remontados lado a lado com a anotação e os campos que saem para o
geocodebr. Cada exemplo vem com município/UF e origem no cabeçalho.

Sem `--modelo`, os exemplos vêm do fold 0 da validação cruzada, então o modelo
que os previu nunca os viu; o modelo do fold é cacheado em
`data/modelos/tagger_oof_fold0.crf` e refeito sozinho quando o dataset muda — o
dataset cresce entre execuções, e `--retreinar` ignora o cache. Com
`--modelo data/modelos/tagger_v15.crf`, a página usa esse tagger sobre o recorte
de teste que o `treinar` gravou no banco, e a saída vira
`data/visualizacoes/exemplos_tagger_v15.html` (um arquivo por modelo).

A escolha é por diversidade de estrutura (rural, parcelamento, referência, ruído,
erro), não por acerto, e a página mostra a taxa real do recorte no topo.
`--alvo N` muda o tamanho da amostra: as cotas de cada seção crescem junto e o
que as categorias estruturais não cobrem é completado em "Outros exemplos",
sempre puxando a origem menos representada.

O template é `src/crf_endereco/visualizacao/exemplo.html` (CSS e JS, sem CDN): o
comando só injeta o JSON dos exemplos, então dá para mexer no visual sem tocar no
Python.

## Como explorar o dataset

`crf explorar` é a versão de leitura do pipeline: **não escreve no banco**.
Responde "onde o modelo sofre?" com as mesmas lentes da etiquetagem e mostra,
caso a caso, as três camadas que explicam um endereço: o alvo atual (o que a LLM
respondeu), a previsão do CRF com a probabilidade de cada token, e o histórico
de reetiquetação. No fim, "10% divergem" vira "estes casos, por isto".

```bash
crf explorar data/anotado/dataset.sqlite                      # 20 mais difíceis
crf explorar data/anotado/dataset.sqlite --divergentes -l 4 --detalhar
crf explorar data/anotado/dataset.sqlite --revisados -l 10 --recorte treino
crf explorar data/anotado/dataset.sqlite --pendentes --uf DF --busca "asa norte"
```

A lista sai ordenada pelo que mais dói, com o `#` de cada caso:

```text
3 caso(s) · revisados: 1 rótulo mantido · 2 concorda com o CRF
#        conf   endereço                   sinal
1   0.45/0.42   PARQUE VILLE MUNICIPAL     rótulo mantido
2   0.46/0.34   Q SAAN QUADRA 4 915 Lote    concorda com o CRF
```

- `--divergentes` olha o que o modelo erra no **próprio** rótulo de treino e
  ordena por tokens trocados (o caso completo do `etiquetar lote --divergentes`,
  sem gastar chamada).
- `--revisados` olha as linhas com `meta.revisoes` e resume o placar dos
  vereditos: `rótulo mantido` (o modelo é que erra), `concorda com o CRF` (o
  rótulo antigo era o problema) e `rótulo novo` (terceira etiqueta). A coluna
  `antes` da tabela token a token é o rótulo que treinou o modelo.
- `--pendentes` troca o alvo pelas linhas nunca etiquetadas: é o CRF decidindo
  sozinho, sem gabarito para comparar.
- `--recorte treino|teste` restringe ao papel que o modelo teve no recorte
  gravado pelo `treinar`; `todos` (padrão) não restringe.
- Sem critério nenhum, a ordem é a confiança do CRF (média/mínima do endereço,
  do mais perdido ao mais seguro) e o `sinal` mostra o token mais duvidoso.

`--detalhar` disseca **todos** os casos da lista: contexto (origem, UF,
município, lote, recorte, LLM, extras), a tabela token a token e os segmentos
verbatim da resposta atual. Como o `--detalhar` segue a lista, `-l` é que decide
quanto sai.

```text
────────────────── #1 PARQUE VILLE MUNICIPAL ──────────────────
origem=aneel_uc_pj · uf=AM · município=MANAUS · recorte=tagger_v13/treino
confiança média 0.45 · mínima 0.42 · pior token 'MUNICIPAL' (I_LOCALIDADE)
revisado por tagger_v13 (1 revisão) · rótulo mantido
token     antes            atual            crf              p         2ª
PARQUE    B_EMPREENDIMENTO B_EMPREENDIMENTO B_LOCALIDADE 0.472 B_EMP 0.37
VILLE     I_EMPREENDIMENTO I_EMPREENDIMENTO I_LOCALIDADE 0.461 I_EMP 0.37
MUNICIPAL I_EMPREENDIMENTO I_EMPREENDIMENTO I_LOCALIDADE 0.419 I_EMP 0.38
  empreendimento     PARQUE VILLE MUNICIPAL
```

`p` é a probabilidade marginal da tag prevista e `2ª` a concorrente mais
próxima: quando as duas empatam, o token é o que decide o caso. O traço na
coluna `atual` (com o aviso `sem alvo`) marca endereço nunca etiquetado, e
`erro guardado na linha` mostra o motivo de uma linha que falhou.

## Como o lote é sorteado

`crf etiquetar lote` não pega "os N primeiros": `pendentes()` sorteia com
`row_number() OVER (PARTITION BY uf, origem ORDER BY random())` e ordena por essa
rodada, o que intercala as células (UF, origem) — a primeira linha de cada célula
vem antes da segunda de qualquer uma. Dentro da rodada, a célula com menos
anotações vem primeiro, o que empurra o lote para o que ainda não foi coberto.
Tudo em uma consulta (`anotacao/pendentes.py`). `--sem-balancear` deixa só o
sorteio, sem intercalar células.

`--limite/-l` conta **endereços**, e é aplicado depois de montar os lotes: cortar
antes dava lotes de um endereço só, porque o sorteio entrega no máximo um de
cada célula. O último lote pode ficar menor que `--tamanho-lote`.

## Como o lote é etiquetado: N endereços por conversa

`--tamanho-lote/-b` (padrão 5) manda vários endereços na **mesma conversa**: o
prompt de sistema (≈7,7k tokens) e o schema das ferramentas são pagos uma vez
para o grupo, não uma vez por endereço. O grupo é formado dentro da mesma célula
(UF, município, origem) — vizinhos compartilham contexto e consultas ao CNEFE.
Quando a célula não tem endereços suficientes, a sobra fecha com os vizinhos do
**município**, qualquer origem; se nem isso, vira lote parcial. Misturar
municípios nunca: é onde a consulta ao CNEFE deixa de valer para o vizinho.

- `responder` recebe `respostas`, uma por endereço, com `indice` = o número do
  bloco `[n]` do pedido.
- A validação é por endereço (`_problemas`): o trecho que não existe verbatim
  **naquele** endereço volta sozinho no pedido de correção, e o endereço que já
  estava certo não é pedido de novo. O que estoura `--tolerancia-erro` vira erro
  daquela linha; os vizinhos ficam com a resposta que já tinham.
- Ferramenta chamada no lote serve ao grupo inteiro (é a razão de agrupar por
  célula); o prompt manda a LLM dizer a que índice a consulta se refere.

Medido com `deepseek-v4.1-flash`, Salvador/siase, `-c 1 -n 4`: `-b 1` rende
10,2 s por endereço, `-b 4` rende 5,3 s e `-b 8` rende 6,0 s — o ganho satura
perto de 4–6, porque o lote maior gasta mais rodadas até todos responderem. O
lote compõe com `--concorrencia`, que ataca a latência por rodada.

Quando um filtro do CRF rodou, cada lote anuncia a própria dificuldade no momento
em que sai da fila: média geométrica das probabilidades dos tokens e a do token
**menos** confiável, endereço a endereço. No começo da execução nada é impresso —
o lote inteiro, com centenas de endereços, ocupava a tela antes da primeira
chamada.

Ctrl+C interrompe de forma ordenada: nada novo é enfileirado, os lotes em voo
terminam e são gravados, e o resumo mostra quantos ficaram de fora. O segundo
Ctrl+C mata o processo na hora (as threads do pool não são daemon: sair pelo
caminho normal ainda esperaria a requisição em curso).

## Estrutura

| caminho | papel |
|---|---|
| `config.py` | caminhos (dados, tagger) e `Config` do ambiente (LLM) |
| `registro.py` | o registro a etiquetar e a normalização dos campos das bases |
| `dataset.py` | único acesso ao SQLite anotado (gravar, ler, exemplos do modelo, recorte de treino/teste) |
| `ui.py` | console e barra de progresso |
| `features/` | normalização, tokenização e features do CRF (paridade com o Rust, exceto o léxico de municípios) |
| `rotulos.py` | segmentos verbatim → rótulos BIO |
| `modelo/crf.py` | dados de treino, treino, tuning, tagger e inferência |
| `modelo/estresse.py` | perturbações fixas do `avaliar --estresse` |
| `modelo/relatorio.py` | métricas e relatório de avaliação |
| `anotacao/agente.py` | prompt, loop reAct e validação da resposta da LLM |
| `anotacao/ferramentas.py` | tools expostas à LLM (CNEFE, busca web, fetch) |
| `anotacao/cliente_http.py` | HTTP com retry e backoff |
| `anotacao/pendentes.py` | recorte e sorteio do lote |
| `anotacao/filtro_crf.py` | filtros pelas previsões do CRF (`--apenas-tipos`, `--incertos`, `--incertos-media`, `--divergentes`) |
| `anotacao/lote.py` | montagem dos lotes, execução em paralelo e gravação |
| `anotacao/populacao/` | uma base pública por arquivo (`Fonte` = SQL + mapeamento) |
| `geocode/comparacao.py` | comparação bruto vs segmentado (relatórios) |
| `segmentador_rust.py` | único adaptador do binário do `enderecobr_rs` |
| `cli/` | cola do typer: `producao`, `modelo`, `geocode`, `explicar`, `explorar` |
| `cli/filtros.py` | opções de recorte compartilhadas por `etiquetar lote` e `explorar` |

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
