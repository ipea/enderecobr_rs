# Changelog

Mudanças do crate `enderecobr_rs` e do pacote Python `enderecobr`. Uma versão
descreve os dois juntos, porque são publicados com o mesmo número.

O formato segue o [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/) e o
versionamento é o [SemVer](https://semver.org/lang/pt-BR/). O que é anterior à
0.7.0 está nas [releases do GitHub](https://github.com/ipea/enderecobr_rs/releases).

## [Não publicado]

## [0.8.0] - 2026-11-19

- Modelo novo: `modelo-crf-v0.3.0` (1,4 MB contra 0,7 MB do `modelo-crf-v0.2.1`).
  Treinado com o aumento de dados do pipeline: cada exemplo ganha até três
  variantes com o alvo original — sem a pontuação dispensável, sem o código `O`
  que abre o texto da base e com os dígitos trocados por outros de mesmo
  tamanho — para o modelo parar de usar pontuação e valor de número como pista.
- Na validação cruzada de 3 folds (11.007 endereços) o aumento levou o endereço
  perfeito de 66,7% para 67,6% e, no DF, de 47,8% para 51,5%. No recorte de teste
  gravado (1.147 endereços) o modelo novo acerta 90,4% dos tokens e 68,3% dos
  endereços inteiros (70,6% ignorando ruído de fronteira).
- Passa a reconhecer o CEP depois da cabeça `CEP` (`cep 01000-000`), que todas
  as versões anteriores jogavam em `O`.

## [0.7.4] - 2026-11-13

- **Breaking**: Simplificando mais ainda as dependências do pacote: agora serde só
  é utilizado nos CLIs.
- Remove a dependência da lib `dirs` que só servia para pegar a pasta de cache do sistema atual.

## [0.7.3] - 2026-11-13

- Forçando novamente uma nova documentação para o Python.

## [0.7.1] - 2026-11-13

- Forçando reenvio para o Pypi após erro de build.

## [0.7.0] - 2026-11-13

### Rust

- **Breaking:** nenhuma feature vem ligada por padrão (`default = []`). Quem usava
  `estruturar_endereco` ou `segmentar_endereco` passa a precisar de
  `features = ["separador", "download"]`; quem já distribui o arquivo do modelo
  fica só com `separador`.
- A documentação publicada no docs.rs continua completa: a doc é gerada com
  `separador` e `download` e cada item condicionado indica a feature exigida.

### Python

- O wheel passa a ser construído só com `separador`: `obter_modelo` foi para o
  lado Python (`urllib`), então a extensão não carrega pilha TLS nem código C.
  Com isso o wheel volta a ser construído para todas as plataformas — com
  `download`, `aarch64` falhava e `armv7`, `ppc64le` e `s390x` nem eram
  possíveis.
- O download grava num arquivo temporário ao lado do destino antes de renomear,
  então uma interrupção não deixa modelo truncado no lugar.
- `segmentar_endereco`, `estruturar_endereco` e `segmentar_enderecos` seguem
  baixando o modelo na primeira chamada, como antes.
