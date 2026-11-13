#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Sobe uma versão da biblioteca e, opcionalmente, um modelo CRF novo.

Aponta as versões e as constantes do modelo, fecha tudo num único commit
tagueado e publica o modelo como asset de uma release do GitHub. Os testes de
integração são rodados com o modelo novo antes de qualquer alteração.

    ./bump_versao.py [-n|--dry-run] <versão>
    ./bump_versao.py [-n|--dry-run] <versão> <versão do modelo> <caminho do modelo>
    ./bump_versao.py 0.6.0 0.3.0 ~/modelos/tagger_novo.crf

    ./bump_versao.py --notas <versão>   # extrai a seção do CHANGELOG e sai
"""

from __future__ import annotations

import argparse
import difflib
import os
import re
import subprocess
import sys
import tempfile
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import NoReturn

ARQUIVO_CONSTANTES = Path("src/separador_endereco/modelo.rs")
ARQUIVOS_VERSAO = (
    Path("Cargo.toml"),
    Path("bindings/python/pyproject.toml"),
    Path("bindings/python/Cargo.toml"),
)
README = Path("README.md")
CHANGELOG = Path("CHANGELOG.md")
URL_RELEASE = "https://github.com/ipea/enderecobr_rs/releases/download"
NAO_PUBLICADO = "## [Não publicado]"
SEMVER = re.compile(r"^\d+\.\d+\.\d+$")
LINHA_VERSAO = re.compile(r'(?m)^version = ".*"$')
LINHA_INSTALACAO = re.compile(r'(?m)^(enderecobr_rs = \{ version = )"[^"]*"')
URL_MODELO = re.compile(r'(releases/download/)[^/"]+(/tagger\.crf)')
CONST_VERSAO_MODELO = re.compile(r'(?m)^pub const VERSAO_MODELO: &str = "[^"]*";$')


def erro(mensagem: str) -> NoReturn:
    print(f"Erro: {mensagem}", file=sys.stderr)
    raise SystemExit(1)


def rodar(*comando: str, env: dict[str, str] | None = None) -> None:
    print("+", " ".join(comando), file=sys.stderr)
    _ = subprocess.run(comando, check=True, env={**os.environ, **env} if env else None)


def gravar_conferindo(
    caminho: Path, novo: str, conferir: Callable[[str], bool], esperado: str
) -> None:
    if not conferir(novo):
        antigo = caminho.read_text(encoding="utf-8")
        _ = sys.stderr.writelines(
            difflib.unified_diff(
                antigo.splitlines(keepends=True),
                novo.splitlines(keepends=True),
                fromfile=str(caminho),
                tofile=f"{caminho} (proposto)",
            )
        )
        erro(f"substituição não deu {esperado}; {caminho} não foi alterado")
    _ = caminho.write_text(novo, encoding="utf-8")


def primeira_linha_versao(texto: str) -> str:
    achado = LINHA_VERSAO.search(texto)
    return achado.group(0) if achado else ""


def atualizar_versoes(versao: str) -> None:
    for caminho in ARQUIVOS_VERSAO:
        texto = caminho.read_text(encoding="utf-8")
        novo = LINHA_VERSAO.sub(f'version = "{versao}"', texto, count=1)
        gravar_conferindo(
            caminho,
            novo,
            lambda t: primeira_linha_versao(t) == f'version = "{versao}"',
            "na primeira linha `version = `",
        )


def atualizar_readme(versao: str) -> None:
    novo = LINHA_INSTALACAO.sub(
        rf'\g<1>"{versao}"', README.read_text(encoding="utf-8")
    )
    gravar_conferindo(
        README,
        novo,
        lambda t: t.count(f'enderecobr_rs = {{ version = "{versao}" }}') == 1,
        "exatamente um exemplo de instalação",
    )


def atualizar_constantes(tag: str) -> None:
    texto = ARQUIVO_CONSTANTES.read_text(encoding="utf-8")
    novo = CONST_VERSAO_MODELO.sub(
        f'pub const VERSAO_MODELO: &str = "{tag}";',
        URL_MODELO.sub(rf"\g<1>{tag}\g<2>", texto),
    )
    gravar_conferindo(
        ARQUIVO_CONSTANTES,
        novo,
        lambda t: t.count(f"download/{tag}/tagger.crf") == 1
        and t.splitlines().count(f'pub const VERSAO_MODELO: &str = "{tag}";') == 1
        and not any(linha.count("pub const") > 1 for linha in t.splitlines()),
        "exatamente uma URL e uma constante do modelo",
    )


def corpo_da_secao(texto: str, inicio: int) -> str:
    proxima = texto.find("\n## [", inicio)
    return texto[inicio : len(texto) if proxima == -1 else proxima]


def atualizar_changelog(versao: str, hoje: str) -> None:
    texto = CHANGELOG.read_text(encoding="utf-8")
    if texto.count(NAO_PUBLICADO) != 1:
        erro(f"{CHANGELOG}: esperava exatamente uma seção {NAO_PUBLICADO}")

    inicio = texto.index(NAO_PUBLICADO) + len(NAO_PUBLICADO)
    if not any(
        linha.startswith("- ") for linha in corpo_da_secao(texto, inicio).splitlines()
    ):
        erro(f"{CHANGELOG}: a seção {NAO_PUBLICADO} está vazia")

    cabecalho = f"## [{versao}] - {hoje}"
    novo = texto.replace(NAO_PUBLICADO, f"{NAO_PUBLICADO}\n\n{cabecalho}", 1)
    gravar_conferindo(
        CHANGELOG,
        novo,
        lambda t: t.count(NAO_PUBLICADO) == 1 and t.count(cabecalho) == 1,
        f"uma seção {NAO_PUBLICADO} e uma {cabecalho}",
    )


def ler_notas(versao: str) -> str:
    texto = CHANGELOG.read_text(encoding="utf-8")
    marca = f"## [{versao}]"
    if marca not in texto:
        return ""
    inicio = texto.index(marca) + len(marca)
    return corpo_da_secao(texto, inicio).split("\n", 1)[-1].strip()


def validar_tags(versao: str, tag_modelo: str) -> None:
    if subprocess.run(
        ["git", "rev-parse", "-q", "--verify", f"refs/tags/v{versao}"],
        capture_output=True,
    ).returncode == 0:
        erro(f"tag v{versao} já existe. Remova com git tag -d v{versao}")

    if tag_modelo and subprocess.run(
        ["gh", "release", "view", tag_modelo], capture_output=True
    ).returncode == 0:
        erro(f"release {tag_modelo} já existe")


def validar_modelo(caminho: Path) -> None:
    if not caminho.is_file():
        erro(f"modelo não encontrado: {caminho}")
    if caminho.read_bytes()[:4] != b"lCRF":
        erro(f"{caminho} não parece um modelo do crfsuite")


def publicar_modelo(caminho: Path, tag: str, url: str) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        asset = Path(tmp, "tagger.crf")
        _ = asset.write_bytes(caminho.read_bytes())
        rodar("gh", "release", "create", tag, str(asset), "--title", tag,
              "--notes", f"Modelo CRF {tag}.")

    if subprocess.run(["curl", "-sfIL", url], capture_output=True).returncode != 0:
        erro(f"asset não acessível em {url}")


def empurrar(versao: str) -> None:
    for comando in (
        ("git", "push", "origin", "HEAD"),
        ("git", "push", "origin", f"v{versao}"),
    ):
        try:
            rodar(*comando)
        except subprocess.CalledProcessError as falha:
            print(
                "\n".join(
                    [
                        f"\nErro: `{' '.join(comando)}` falhou.",
                        "O commit e a tag continuam locais.",
                        "Para terminar:",
                        "  git push origin HEAD",
                        f'  git push origin "v{versao}"',
                        "",
                        "Se o commit ainda não chegou ao remoto, dá para desfazer:",
                        "  git reset HEAD^",
                        f'  git tag -d "v{versao}"',
                    ]
                ),
                file=sys.stderr,
            )
            raise SystemExit(1) from falha


class Argumentos(argparse.Namespace):
    versao: str = ""
    versao_modelo: str | None = None
    modelo: str | None = None
    dry_run: bool = False
    notas: bool = False
    sem_push: bool = False


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Sobe uma versão da biblioteca e, opcionalmente, um modelo CRF."
    )
    _ = parser.add_argument("versao", help="versão da biblioteca (ex.: 0.6.0)")
    _ = parser.add_argument(
        "versao_modelo", nargs="?", help="versão do modelo (ex.: 0.3.0)"
    )
    _ = parser.add_argument("modelo", nargs="?", help="caminho do arquivo do modelo")
    _ = parser.add_argument(
        "-n", "--dry-run", action="store_true", help="só mostra o plano"
    )
    _ = parser.add_argument(
        "--notas", action="store_true", help="extrai a seção do CHANGELOG e sai"
    )
    _ = parser.add_argument(
        "--sem-push",
        action="store_true",
        help="termina no commit e na tag, sem empurrar para o remoto",
    )
    argumentos = parser.parse_args(namespace=Argumentos())

    versao = argumentos.versao.removeprefix("v")
    versao_modelo = (argumentos.versao_modelo or "").removeprefix("v")
    caminho_modelo = Path(argumentos.modelo).expanduser() if argumentos.modelo else None

    if bool(versao_modelo) != (caminho_modelo is not None):
        erro("informe a versão do modelo e o caminho do modelo, ou nenhum dos dois")
    if not SEMVER.match(versao):
        erro(f"versão inválida: {versao} (esperado MAJOR.MINOR.PATCH, ex.: 0.6.0)")
    if versao_modelo and not SEMVER.match(versao_modelo):
        erro(f"versão de modelo inválida: {versao_modelo} (ex.: 0.3.0)")

    if argumentos.notas:
        print(ler_notas(versao))
        return

    tag_modelo = ""
    url_modelo = ""
    if versao_modelo and caminho_modelo:
        tag_modelo = f"modelo-crf-v{versao_modelo}"
        url_modelo = f"{URL_RELEASE}/{tag_modelo}/tagger.crf"
        validar_modelo(caminho_modelo)
        print(f"Rodando os testes de sanidade com {caminho_modelo}", file=sys.stderr)
        rodar(
            "cargo",
            "test",
            "--quiet",
            "--test",
            "crf",
            "--features",
            "separador",
            env={
                "ENDERECOBR_MODELO": str(caminho_modelo),
                "ENDERECOBR_MODELO_SEM_DOWNLOAD": "1",
                "TESTE_CRF_EXIGE_MODELO": "1",
            },
        )
        print("Sanidade ok: testes de integração aprovados", file=sys.stderr)

    validar_tags(versao, tag_modelo)

    sufixo = f" (modelo {tag_modelo})" if tag_modelo else ""
    hoje = date.today().isoformat()

    if argumentos.dry_run:
        alvos = ", ".join(map(str, ARQUIVOS_VERSAO))
        plano = [
            "",
            f"[dry-run] em {alvos}:\n  version -> {versao}",
            f"[dry-run] em {README}:\n  exemplo de instalação -> "
            + f'enderecobr_rs = {{ version = "{versao}" }}',
            f"[dry-run] em {CHANGELOG}:\n"
            + f"  {NAO_PUBLICADO[3:]} -> ## [{versao}] - {hoje}",
        ]
        if tag_modelo:
            plano.append(
                "\n".join(
                    [
                        f"[dry-run] em {ARQUIVO_CONSTANTES}:",
                        f"  MODEL_DOWNLOAD_PATH -> .../download/{tag_modelo}/tagger.crf",
                        f"  VERSAO_MODELO       -> {tag_modelo}",
                        f"[dry-run] gh release create {tag_modelo} "
                        + f"<tagger.crf> --title {tag_modelo}",
                    ]
                )
            )
        plano.extend(
            [
                f"[dry-run] commit: chore: release v{versao}{sufixo}",
                f"[dry-run] tag: v{versao}",
            ]
        )
        if argumentos.sem_push:
            plano.append("[dry-run] push: não (--sem-push)")
        else:
            plano.extend(
                [
                    "[dry-run] git push origin HEAD",
                    f"[dry-run] git push origin v{versao}",
                ]
            )
        plano.append("[dry-run] nada foi alterado")
        print("\n".join(plano))
        return

    if tag_modelo and caminho_modelo:
        publicar_modelo(caminho_modelo, tag_modelo, url_modelo)
        atualizar_constantes(tag_modelo)

    atualizar_versoes(versao)
    atualizar_readme(versao)
    atualizar_changelog(versao, hoje)

    rodar("cargo", "check", "--features", "separador,download")
    rodar("cargo", "check", "--manifest-path", "bindings/python/Cargo.toml")
    rodar("uv", "sync", "--directory", "bindings/python")

    arquivos = [
        Path("Cargo.toml"),
        Path("Cargo.lock"),
        README,
        CHANGELOG,
        Path("bindings/python/pyproject.toml"),
        Path("bindings/python/Cargo.toml"),
        Path("bindings/python/Cargo.lock"),
        Path("bindings/python/uv.lock"),
    ]
    if tag_modelo:
        arquivos.append(ARQUIVO_CONSTANTES)

    rodar("git", "add", *map(str, arquivos))
    rodar("git", "commit", "-m", f"chore: release v{versao}{sufixo}")
    rodar("git", "tag", f"v{versao}")

    if not argumentos.sem_push:
        empurrar(versao)

    situacao = (
        f"Versão {versao} commitada e tagueada localmente (--sem-push)."
        if argumentos.sem_push
        else f"Versão {versao} publicada: commit, tag e push feitos."
    )
    print(
        f"\n{situacao}"
        + (f"\nModelo publicado em {url_modelo}" if tag_modelo else "")
        + "\n"
        + f"""
O push da tag dispara: publish-cargo (crates.io), maturin (PyPI), GH Release,
atualizar-snapshot e trigger-readthedocs.

Depois confira:
  gh run list --limit 6         # resultado de cada workflow
  gh release view "v{versao}"    # notas saídas do CHANGELOG

Para reverter, antes que a tag chegue ao remoto:
  git reset HEAD^
  git tag -d "v{versao}"
"""
    )


if __name__ == "__main__":
    main()
