from crf_endereco.visualizacao import CATEGORIAS, SECAO_ERROS, SECAO_SOBRA, escolher

ORIGENS = ("siase", "cafir", "cadunico", "cneas", "aneel_uc_pj")
TIPOS = ("logradouro", "parcela", "complemento", "nucleo_rural", "localidade")


def _candidato(i: int, *, ok: bool = True) -> dict[str, object]:
    """Candidato minimo: so os campos que `escolher` le."""
    tipo = TIPOS[(i // len(ORIGENS)) % len(TIPOS)]
    return {
        "endereco": f"RUA {i}",
        "origem": ORIGENS[i % len(ORIGENS)],
        "tipos": [tipo],
        "ok": ok,
        "diferencas": 0 if ok else 1,
        "assinatura": () if ok else (("RUA", "B_LOGRADOURO", "I_LOGRADOURO"),),
        "n_tokens": 4 + i % 20,
        "n_complementos": 1 if tipo == "complemento" else 0,
    }


def test_escolher_nao_repete_endereco_e_respeita_o_alvo():
    candidatos = [_candidato(i) for i in range(400)]

    escolhidos = escolher(candidatos, 200)

    assert len(escolhidos) == 200
    enderecos = [e["endereco"] for e in escolhidos]
    assert len(set(enderecos)) == len(enderecos)


def test_escolher_engorda_as_secoes_com_o_alvo():
    candidatos = [_candidato(i) for i in range(400)]

    pequeno = escolher(candidatos, 50)
    grande = escolher(candidatos, 200)

    parcelamento = "Parcelamento (quadra, lote, gleba)"
    assert sum(1 for e in grande if e["categoria"] == parcelamento) > sum(
        1 for e in pequeno if e["categoria"] == parcelamento
    )


def test_escolher_completa_a_sobra_sem_inventar_categoria():
    candidatos = [_candidato(i, ok=i % 4 != 0) for i in range(400)]
    secoes = {nome for nome, _, _ in CATEGORIAS} | {SECAO_SOBRA, SECAO_ERROS}

    escolhidos = escolher(candidatos, 100)

    assert len(escolhidos) == 100
    assert {e["categoria"] for e in escolhidos} <= secoes
    assert all(e["ok"] or e["categoria"] == SECAO_ERROS for e in escolhidos)


def test_escolher_erros_nao_repetem_a_mesma_assinatura():
    candidatos = [_candidato(i, ok=False) for i in range(40)]

    escolhidos = escolher(candidatos, 50)

    erros = [e for e in escolhidos if e["categoria"] == SECAO_ERROS]
    assert len(erros) == 1
