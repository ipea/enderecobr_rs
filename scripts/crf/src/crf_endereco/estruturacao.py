"""Segmentos remontados para os campos do endereco (espelho de `estruturacao.rs`)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import enderecobr

# Campos do `Endereco`, na ordem em que `formatar` junta.
CAMPOS = ("logradouro", "numero", "complemento", "localidade", "cep")

# Função de padronização de cada campo (`padronizar_in_place` no Rust).
PADRONIZADORES = {
    "logradouro": enderecobr.padronizar_logradouros,
    "numero": enderecobr.padronizar_numeros,
    "complemento": enderecobr.padronizar_complementos,
    "localidade": enderecobr.padronizar_bairros,
    "cep": enderecobr.padronizar_cep_leniente,
}


def estruturar_segmentos(
    segmentos: Sequence[Mapping[str, str]],
) -> dict[str, str | None]:
    """Espelha `estruturar_segmentos` do Rust (`estruturacao.rs`).

    Cada trecho fica no primeiro campo livre da sua lista de preferência; trecho
    sem lista, ou com todos os campos dela já ocupados, é descartado. Parcela e
    complemento são concatenáveis: entram em sequência no campo já preenchido.
    """
    campos: dict[str, str | None] = dict.fromkeys(CAMPOS)
    for i, segmento in enumerate(segmentos):
        preferidos, concatenar = campos_preferidos(
            segmento.get("tipo", ""),
            segmentos[i - 1].get("tipo") if i else None,
        )
        for campo in preferidos:
            valor = segmento.get("valor", "")
            if campos[campo] is None:
                campos[campo] = valor
                break
            if concatenar:
                campos[campo] = f"{campos[campo]} {valor}"
                break
    return campos


def campos_preferidos(tipo: str, anterior: str | None) -> tuple[list[str], bool]:
    """Campos que o trecho pode ocupar, na ordem de preferência, e se concatenam.

    A lista vazia descarta o trecho. A ordem dos casos é a mesma do Rust: o
    primeiro que casa manda.
    """
    if tipo == "logradouro":
        return ["logradouro"], False
    if tipo in ("numero", "quilometragem_via"):
        return ["numero", "complemento"], False
    if tipo == "cep":
        return ["cep"], False
    if tipo == "parcela":
        if anterior == "logradouro":
            return ["logradouro"], True
        return ["logradouro", "complemento"], True
    if tipo in (
        "nucleo_rural",
        "recurso_natural",
        "empreendimento",
        "ponto_referencia",
    ):
        return ["logradouro", "localidade"], False
    if tipo == "complemento":
        return ["complemento"], True
    if tipo == "localidade":
        return ["localidade"], False
    return [], False


def padronizar(campos: Mapping[str, str | None]) -> dict[str, str | None]:
    return {
        campo: None if valor is None else PADRONIZADORES[campo](valor)
        for campo, valor in campos.items()
    }


def formatar(campos: Mapping[str, str | None]) -> str:
    return ", ".join(valor.strip() for valor in campos.values() if valor is not None)
