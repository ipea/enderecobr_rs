# Changelog

Mudanças do crate `enderecobr_rs` e do pacote Python `enderecobr`. Uma versão
descreve os dois juntos, porque são publicados com o mesmo número.

O formato segue o [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/) e o
versionamento é o [SemVer](https://semver.org/lang/pt-BR/). O que é anterior à
0.7.0 está nas [releases do GitHub](https://github.com/ipea/enderecobr_rs/releases).

## [Não publicado]

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
