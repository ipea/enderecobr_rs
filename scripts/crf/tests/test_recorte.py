import sqlite3
from pathlib import Path

from crf_endereco.dataset import criar_banco, gravar_recorte, ler_recorte
from crf_endereco.features import tokenize
from crf_endereco.modelo.crf import Exemplos, nome_do_modelo, separar_por_recorte
from crf_endereco.modelo.estresse import (
    FAMILIAS,
    abreviar_tipo,
    truncar_tipo,
    truncar_tokens,
    typo_no_tipo,
    typos_no_endereco,
)


def banco_com(hashes: list[str]) -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    criar_banco(conn)
    for i, hash_ in enumerate(hashes):
        _ = conn.execute(
            "INSERT INTO enderecos (id, endereco, origem, lote, hash_endereco,"
            " data_criacao) VALUES (?, ?, 'origem', 'lote', ?, '2026-01-01')",
            (i, f"R {i}", hash_),
        )
    conn.commit()
    return conn


def exemplos_com(hashes: list[str]) -> Exemplos:
    return Exemplos(
        x=[[{"bias": 1.0}] for _ in hashes],
        y=[["B_LOGRADOURO"] for _ in hashes],
        tokens=[["RUA"] for _ in hashes],
        categorias=[["origem", "SP"] for _ in hashes],
        hashes=hashes,
    )


def test_criar_banco_adiciona_recorte_em_banco_criado_antes():
    conn = sqlite3.connect(":memory:")
    _ = conn.executescript(
        """
        CREATE TABLE enderecos (
            id INTEGER PRIMARY KEY,
            endereco TEXT NOT NULL,
            extras TEXT NOT NULL DEFAULT '',
            meta TEXT NOT NULL DEFAULT '{}',
            resposta_llm TEXT,
            origem TEXT NOT NULL,
            origem_id TEXT,
            municipio TEXT,
            uf TEXT,
            lote TEXT NOT NULL,
            hash_endereco TEXT NOT NULL UNIQUE,
            data_criacao TEXT NOT NULL,
            data_processamento TEXT,
            llm TEXT
        );
        """
    )

    criar_banco(conn)

    colunas = {linha[1] for linha in conn.execute("PRAGMA table_info(enderecos)")}
    assert "recorte" in colunas


def test_recorte_gravado_volta_pelo_banco():
    conn = banco_com(["h1", "h2", "h3"])

    gravar_recorte(conn, "tagger", treino=["h1", "h2"], teste=["h3"])

    assert ler_recorte(conn, "tagger") == {"treino": {"h1", "h2"}, "teste": {"h3"}}


def test_recorte_e_por_modelo():
    conn = banco_com(["h1"])
    gravar_recorte(conn, "tagger", treino=["h1"], teste=[])

    assert ler_recorte(conn, "outro") == {"treino": set(), "teste": set()}


def test_recorte_de_outro_modelo_nao_e_apagado():
    # A coluna `recorte` guarda um modelo so: treinar o v16 apagava o recorte do
    # v15 e nao dava mais para compara-los no teste de cada um.
    conn = banco_com(["h1", "h2", "h3", "h4"])
    gravar_recorte(conn, "v15", treino=["h1"], teste=["h2"])
    gravar_recorte(conn, "v16", treino=["h3"], teste=["h4"])

    assert ler_recorte(conn, "v15") == {"treino": {"h1"}, "teste": {"h2"}}
    assert ler_recorte(conn, "v16") == {"treino": {"h3"}, "teste": {"h4"}}


def test_separar_por_recorte_preserva_a_ordem_do_banco():
    exemplos = exemplos_com(["h1", "h2", "h3"])

    treino, teste = separar_por_recorte(
        exemplos, {"treino": {"h1", "h2"}, "teste": {"h3"}}
    )

    assert treino.hashes == ["h1", "h2"]
    assert teste.hashes == ["h3"]


def test_separar_por_recorte_deixa_de_fora_endereco_sem_papel():
    exemplos = exemplos_com(["h1", "h2", "h3"])

    treino, teste = separar_por_recorte(exemplos, {"treino": {"h1"}, "teste": {"h3"}})

    assert treino.hashes == ["h1"]
    assert teste.hashes == ["h3"]


def test_nome_do_modelo_e_o_nome_do_arquivo_sem_extensao():
    assert nome_do_modelo(Path("data/modelos/tagger.crf")) == "tagger"


def test_todas_as_familias_preservam_a_contagem_de_tokens():
    endereco = "RUA DAS FLORES 123 APTO 45 - CENTRO"

    for nome, perturbar in FAMILIAS:
        assert len(tokenize(perturbar(endereco))) == len(tokenize(endereco)), nome


def test_abreviacao_usa_a_sigla_do_cadastro():
    assert abreviar_tipo("Avenida Brasil 100") == "AV Brasil 100"


def test_abreviacao_ignora_endereco_sem_tipo_conhecido():
    assert abreviar_tipo("CONJUNTO X 4") == "CJ X 4"
    assert abreviar_tipo("BAIRRO DAS FLORES") == "BAIRRO DAS FLORES"


def test_truncamentos_cortam_so_o_que_e_palavra():
    assert truncar_tipo("Avenida Brasil 100") == "Ave Brasil 100"
    assert truncar_tipo("Rua BR 116") == "Rua BR 116"
    assert truncar_tokens("Avenida Brasil 100") == "Ave Bra 100"


def test_typo_do_tipo_e_reproduzivel_e_mexe_na_palavra():
    endereco = "AVENIDA BRASIL 100"

    assert typo_no_tipo(endereco) == typo_no_tipo(endereco)
    assert typo_no_tipo(endereco) != endereco


def test_typos_do_endereco_nao_mexem_em_numero():
    endereco = "AVENIDA BRASIL 100 200"

    perturbado = typos_no_endereco(endereco)

    assert perturbado.endswith("100 200")
