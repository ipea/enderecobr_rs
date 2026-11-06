"""Testes da DSL de politica: sem geocodebr, sem arquivo, so semantica."""

from __future__ import annotations

from crf_endereco.anotacao.ontologia import TIPOS_SEGMENTO
from scripts.otimizar_politica import (
    MAX_REGRAS,
    Atomo,
    Avaliacao,
    Campo,
    Politica,
    Regra,
    SePreenchido,
    Termo,
    aplicar,
    candidatas,
    regras_de_json,
    regras_para_json,
    regras_para_texto,
    termos_possiveis,
    trocar_regra,
    vizinhas,
    with_termo,
)

LOGRADOURO = Campo.LOGRADOURO
NUMERO = Campo.NUMERO
LOCALIDADE = Campo.LOCALIDADE
IGNORAR = Campo.IGNORAR


def politica(**regras: tuple[Regra, ...]) -> Politica:
    """Politica completa: os tipos nao citados descartam o segmento."""
    base: Politica = dict.fromkeys(TIPOS_SEGMENTO, ())
    base.update(regras)
    return base


def test_json_ida_e_volta_preserva_a_politica():
    regras = (
        Regra(
            (Termo(Atomo.ANTES_TIPO, "numero"), Termo(Atomo.TEM, "logradouro", negado=True)),
            LOCALIDADE,
        ),
        Regra((Termo(Atomo.DONO_UNICO, "logradouro"),), LOGRADOURO, SePreenchido.SUBSTITUIR),
        Regra(),
    )
    assert regras_de_json(regras_para_json(regras)) == regras
    assert regras_de_json(regras_para_json(())) == ()


def test_decision_list_primeira_regra_vence():
    pol = politica(
        parcela=(
            Regra((Termo(Atomo.ANTES_TIPO, "numero"),), IGNORAR),
            Regra((), LOGRADOURO),
        ),
        numero=(Regra((), NUMERO),),
    )
    # depois do numero: descarta; antes dele: logradouro
    assert aplicar(pol, [("numero", "10"), ("parcela", "lote 3")]) == {NUMERO: "10"}
    assert aplicar(pol, [("parcela", "lote 3"), ("numero", "10")]) == {
        LOGRADOURO: "lote 3",
        NUMERO: "10",
    }


def test_manter_e_substituir_decidem_quem_fica_no_campo():
    segs = [("logradouro", "rua a"), ("parcela", "lote 3")]
    manter = politica(logradouro=(Regra((), LOGRADOURO),), parcela=(Regra((), LOGRADOURO),))
    assert aplicar(manter, segs) == {LOGRADOURO: "rua a"}
    substituir = politica(
        logradouro=(Regra((), LOGRADOURO),),
        parcela=(Regra((), LOGRADOURO, SePreenchido.SUBSTITUIR),),
    )
    assert aplicar(substituir, segs) == {LOGRADOURO: "lote 3"}


def test_antes_tipo_distingue_dois_tipos_que_caem_no_mesmo_campo():
    # `referencia` e `numero` ocupam o mesmo campo: so `antes.tipo` separa.
    pol = politica(
        numero=(Regra((), NUMERO),),
        referencia=(Regra((), NUMERO),),
        parcela=(
            Regra((Termo(Atomo.ANTES_TIPO, "referencia"),), LOGRADOURO),
            Regra((Termo(Atomo.ANTES_CAMPO, "numero"),), IGNORAR),
        ),
    )
    assert aplicar(pol, [("referencia", "esquina com"), ("parcela", "lote 3")]) == {
        NUMERO: "esquina com",
        LOGRADOURO: "lote 3",
    }
    assert aplicar(pol, [("numero", "10"), ("parcela", "lote 3")]) == {NUMERO: "10"}


def test_dono_unico_olha_os_tipos_que_disputam_o_campo():
    pol = politica(
        logradouro=(Regra((), LOGRADOURO),),
        numero=(Regra((), NUMERO),),
        nucleo_rural=(
            Regra((Termo(Atomo.DONO_UNICO, "logradouro"),), LOGRADOURO),
            Regra((), LOCALIDADE),
        ),
    )
    # sozinho entre os que disputam logradouro: vira logradouro
    assert aplicar(pol, [("nucleo_rural", "sitio mirador"), ("numero", "1")]) == {
        LOGRADOURO: "sitio mirador",
        NUMERO: "1",
    }
    # com um logradouro na linha, deixa de ser dono unico e cai para localidade
    assert aplicar(
        pol, [("logradouro", "rua a"), ("nucleo_rural", "sitio mirador"), ("numero", "1")]
    ) == {LOGRADOURO: "rua a", LOCALIDADE: "sitio mirador", NUMERO: "1"}


def test_vizinhos_andam_um_passo_e_nao_repetem_a_politica_atual():
    atuais = (Regra((Termo(Atomo.ANTES_CAMPO, "numero"),), LOGRADOURO), Regra((), LOCALIDADE))
    vizinhas_ = vizinhas(atuais)
    assert atuais not in vizinhas_
    assert len(vizinhas_) == len(set(vizinhas_))
    # remocao, reordenacao e troca de campo de cada regra estao presentes
    assert (Regra((), LOCALIDADE),) in vizinhas_
    assert (atuais[1], atuais[0]) in vizinhas_
    assert (Regra((Termo(Atomo.ANTES_CAMPO, "numero"),), NUMERO), atuais[1]) in vizinhas_
    # negar o termo e trocar o valor dele
    com_numero = Termo(Atomo.ANTES_CAMPO, "numero")
    negado = trocar_regra(atuais, 0, with_termo(atuais[0], 0, Termo(com_numero.atomo, "numero", True)))
    trocado = trocar_regra(atuais, 0, with_termo(atuais[0], 0, Termo(com_numero.atomo, "localidade")))
    assert negado in vizinhas_
    assert trocado in vizinhas_


def test_termos_possiveis_nao_repete_e_respeita_o_dominio():
    termos = termos_possiveis()
    assert len(termos) == len(set(termos))
    assert Termo(Atomo.PRIMEIRO) in termos
    assert Termo(Atomo.PRIMEIRO, "logradouro") not in termos
    assert Termo(Atomo.ANTES_CAMPO, "ignorar") in termos
    assert Termo(Atomo.DONO_UNICO, "ignorar") not in termos
    assert Termo(Atomo.DONO_UNICO, "localidade", True) in termos


def test_candidatas_param_no_teto_e_podam_termo_sem_suporte():
    segs = [
        [("logradouro", "rua a"), ("numero", "10")],
        [("logradouro", "rua b"), ("numero", "11")],
    ]
    av = Avaliacao(
        estado=["SP", "SP"],
        municipio=["sao paulo", "sao paulo"],
        cep=[None, None],
        segs=segs,
        linhas_por_tipo={"logradouro": [0, 1], "numero": [0, 1]},
    )
    pol = politica(logradouro=(Regra((), LOGRADOURO),), numero=(Regra((), NUMERO),))
    candidatas_ = candidatas(av, pol, "logradouro", [0, 1])
    assert pol["logradouro"] not in candidatas_
    assert all(len(regras) <= MAX_REGRAS for regras in candidatas_)
    # nenhum termo que nao dispara na amostra (nao ha cep nessas linhas)
    assert not any(
        termo.atomo is Atomo.TEM and termo.valor == "cep"
        for regras in candidatas_
        for regra in regras
        for termo in regra.termos
    )


def test_texto_da_politica_e_legivel():
    assert regras_para_texto(()) == "ignorar"
    assert regras_para_texto((Regra((), NUMERO),)) == "sempre => numero/manter"
    condicao = (Termo(Atomo.ANTES_TIPO, "numero"), Termo(Atomo.TEM, "cep", negado=True))
    assert regras_para_texto((Regra(condicao, IGNORAR),)) == "antes.tipo=numero & !tem=cep => ignorar"
