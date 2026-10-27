"""Adaptador do binario Rust do enderecobr_rs."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import typer

from crf_endereco.config import DIR_REPO

BINARIO_LOTE = DIR_REPO / "target" / "release" / "padronizacao-lote"


def comando_segmentacao(binario: Path | None = None) -> list[str]:
    """Comando que le enderecos (stdin) e devolve a segmentacao em JSON."""
    if binario is None:
        for perfil in ("release", "debug"):
            candidato = DIR_REPO / "target" / perfil / "padronizar"
            if candidato.is_file():
                binario = candidato
                break
    if binario is None:
        return [
            "cargo",
            "run",
            "--quiet",
            "--bin",
            "padronizar",
            "--features=cli",
            "segmentacao",
        ]
    return [str(binario), "segmentacao"]


def rodar_segmentacao(
    enderecos: list[str],
    modelo: Path | None = None,
    binario: Path | None = None,
) -> list[str]:
    """Segmenta enderecos com o mesmo modelo que o Python (uma linha por um)."""
    if any("\n" in endereco for endereco in enderecos):
        raise RuntimeError(
            "Endereco com quebra de linha quebra o protocolo do segmentador "
            "(uma linha por endereco)."
        )
    ambiente = dict(os.environ)
    if modelo is not None:
        ambiente["ENDERECOBR_MODELO"] = str(modelo.resolve())
    comando = comando_segmentacao(binario)
    resultado = subprocess.run(
        comando,
        input="\n".join(enderecos),
        capture_output=True,
        text=True,
        check=False,
        cwd=DIR_REPO,
        env=ambiente,
    )
    if resultado.returncode != 0:
        raise RuntimeError(
            f"O segmentador falhou ({comando[0]}): {resultado.stderr.strip()[:500]}"
        )
    saida = resultado.stdout.splitlines()
    if len(saida) != len(enderecos):
        raise RuntimeError(
            f"O segmentador devolveu {len(saida)} linha(s) para "
            f"{len(enderecos)} endereco(s)."
        )
    return saida


def segmentar_lote(
    binario: Path,
    estagio: Path,
    destino: Path,
    n_cores: int,
    manter_chave: bool,
) -> None:
    """Segmenta um parquet de trabalho com o `padronizacao-lote`."""
    if not binario.is_file():
        raise typer.BadParameter(
            f"binario nao encontrado: {binario}\n"
            + "compile com: cargo build --release --bin padronizacao-lote"
        )
    # `-m` e variadico: precisa ser a ultima opcao da linha de comando
    comando = [str(binario), str(estagio), "-o", str(destino), "-e", "endereco"]
    comando += ["-m", "id"]
    if manter_chave:
        comando += ["chave"]
    ambiente = dict(os.environ)
    if n_cores > 0:
        ambiente["POLARS_MAX_THREADS"] = str(n_cores)
        ambiente["RAYON_NUM_THREADS"] = str(n_cores)
    resultado = subprocess.run(comando, env=ambiente, capture_output=True, text=True)
    if resultado.returncode != 0:
        raise typer.BadParameter(
            f"falha ao segmentar ({resultado.returncode}):\n{resultado.stderr.strip()}"
        )
    if resultado.stdout.strip():
        print(resultado.stdout.strip(), flush=True)
    if not destino.exists():
        raise typer.BadParameter(
            f"o segmentador nao gerou {destino}; veja a saida acima"
        )
