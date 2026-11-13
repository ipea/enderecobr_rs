# Changelog

Mudanças do crate `enderecobr_rs` e do pacote Python `enderecobr`. Uma versão
descreve os dois juntos, porque são publicados com o mesmo número.

O formato segue o [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/) e o
versionamento é o [SemVer](https://semver.org/lang/pt-BR/). O que é anterior à
0.7.0 está nas [releases do GitHub](https://github.com/ipea/enderecobr_rs/releases).

## [Não publicado]

### Rust

- **Breaking:** nenhuma feature vem ligada por padrão (`default = []`). Quem usava
  `estruturar_endereco` ou `segmentar_endereco` passa a precisar de
  `features = ["separador", "download"]`; quem já distribui o arquivo do modelo
  fica só com `separador`.
- A documentação publicada no docs.rs continua completa: a doc é gerada com
  `separador` e `download` e cada item condicionado indica a feature exigida.

### Python

- Mesma API e mesmo comportamento: o wheel é construído com `separador` e
  `download`, então `estruturar_endereco` e `obter_modelo` seguem baixando o
  modelo na primeira chamada.
