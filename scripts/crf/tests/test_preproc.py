import pytest

from crf_endereco.features import (
    ExtratorFeature,
    is_pontuacao,
    normalize,
    tokenize,
    tokenize_com_offsets,
)


# ----------------------------
# Utilitários
# ----------------------------
def test_normalize_remove_acentos():
    assert normalize("ação") == "acao"


def test_normalize_maiusculas_e_minusculas():
    assert normalize("ÁbÇ") == "AbC"


def test_normalize_sem_acentos_retorna_igual():
    assert normalize("Rua") == "Rua"


def test_tokenize_basico():
    assert tokenize("Rua das Flores!") == ["Rua", "das", "Flores", "!"]
    assert tokenize("123, teste") == ["123", ",", "teste"]
    assert tokenize("") == []
    assert tokenize("A/B") == ["A", "/", "B"]


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Rua das Flores, 123", ["Rua", "das", "Flores", ",", "123"]),
        (
            "Av. Paulista 1000 - São Paulo",
            ["Av", ".", "Paulista", "1000", "-", "São", "Paulo"],
        ),
        # Não esperava que nº iria ficar junto.
        ("R. Azul, nº 45", ["R", ".", "Azul", ",", "nº", "45"]),
        ("CEP: 01311-200", ["CEP", ":", "01311", "-", "200"]),
        ("Bloco B apto. 12", ["Bloco", "B", "apto", ".", "12"]),
    ],
)
def test_tokenize_casos(text: str, expected: list[str]):
    assert tokenize(text) == expected


def test_tokenize_com_offsets():
    assert tokenize_com_offsets("R. Azul, 45") == [
        ("R", 0),
        (".", 1),
        ("Azul", 3),
        (",", 7),
        ("45", 9),
    ]
    assert tokenize_com_offsets("") == []


def test_is_pontuacao_casos_basicos():
    assert is_pontuacao(",") is True
    assert is_pontuacao("...") is True
    assert is_pontuacao("a") is False
    assert is_pontuacao("") is False


# ----------------------------
# token2features
# ----------------------------


def token2features(sent: list[str], i: int):
    return ExtratorFeature().tokens2features(sent)[i]


def tokens2features(sent: list[str]):
    return ExtratorFeature().tokens2features(sent)


def test_token2features_primeiro_token_basico():
    sent = ["Rua", "das", "Flores"]
    feats = token2features(sent, 0)
    assert "bias" in feats
    assert "0_pos" in feats
    assert "0:RUA" in feats
    assert "0:is_alpha" in feats
    assert "0:tam:3" in feats
    assert "BOS" in feats
    assert "1:DAS" in feats
    assert "1:is_alpha" in feats
    assert "2:FLORES" in feats
    assert "2:is_alpha" in feats

    assert "EOS" not in feats


def test_token2features_token_final():
    sent = ["Rua", "das", "Flores"]
    feats = token2features(sent, 2)
    assert "bias" in feats
    assert "EOS" in feats
    assert "0:FLORES" in feats
    assert "0:is_alpha" in feats
    assert "0:tam:6" in feats
    assert "-1:DAS" in feats
    assert "-1:is_alpha" in feats
    assert "-2:RUA" in feats
    assert "-2:is_alpha" in feats

    assert "BOS" not in feats


def test_token2features_token_meio_com_digito():
    sent = ["Rua", "123", "Centro"]
    feats = token2features(sent, 1)
    assert "0:is_digit" in feats
    assert "0:tam:3" in feats
    assert "0:123" in feats
    assert "-1:RUA" in feats
    assert "1:CENTRO" in feats
    assert "1:is_alpha" in feats
    assert not any("digit_len" in f for f in feats)

    assert "BOS" not in feats
    assert "EOS" not in feats


def test_token2features_token_pontuacao():
    sent = ["Rua", ",", "Centro"]
    feats = token2features(sent, 1)
    assert "0:," in feats
    assert "0:is_punct" in feats
    assert "-1:RUA" in feats
    assert "-1:is_alpha" in feats
    assert "1:CENTRO" in feats
    assert "1:is_alpha" in feats

    assert "EOS" not in feats


def test_token2features_com_token_alfanumerico():
    # O tokenizador separa letras de números, então "A1" é um caso desconhecido.
    sent = ["Rua", "A1", "Centro"]
    feats = token2features(sent, 1)
    assert "0:A1" in feats
    assert "0:is_unknown" in feats
    assert "0:is_alpha" not in feats
    assert "0:tam:2" in feats
    assert "-1:RUA" in feats
    assert "1:CENTRO" in feats

    assert "BOS" not in feats
    assert "EOS" not in feats


def test_token2features_com_pontuacao_entre_palavras():
    sent = ["Rua", ",", "das", "Flores"]
    feats = token2features(sent, 0)
    assert "0:RUA" in feats
    assert "1:DAS" in feats
    assert "2:FLORES" in feats
    assert "tem_pontuacao:1" in feats
    assert "BOS" in feats

    assert "EOS" not in feats


def test_token2features_ignora_pontuacoes_sucessivas():
    sent = ["Rua", ",", ".", "Flores"]
    feats = token2features(sent, 0)
    assert "0:RUA" in feats
    assert "1:FLORES" in feats
    assert "1:is_alpha" in feats
    assert "tem_pontuacao:1" in feats
    assert "BOS" in feats

    assert "EOS" not in feats


def test_token2features_palavra_longa():
    sent = ["Inconstitucionalissimamente"]
    feats = token2features(sent, 0)
    assert "0:INCONSTITUCIONALISSIMAMENTE" in feats
    assert "0:tam:10" in feats
    assert "0:is_alpha" in feats
    assert "BOS" in feats
    assert "EOS" in feats
    assert "bias" in feats


def test_token2features_todos_pontuacao():
    sent = [",", ".", ";"]
    feats = token2features(sent, 1)
    assert "0:is_punct" in feats
    assert "0:." in feats
    assert "0:tam:1" in feats

    assert "BOS" not in feats
    assert "EOS" not in feats
    assert "-1:," not in feats
    assert "1:;" not in feats


def test_token2features_com_token_numerico_longo_zeros():
    sent = ["000000000000012345"]
    feats = token2features(sent, 0)
    assert "0:is_digit" in feats
    assert "0:tam:5" in feats
    assert "0:000000000000012345" in feats


def test_token2features_com_token_numerico_longo():
    sent = ["123456789"]
    feats = token2features(sent, 0)
    assert "0:is_digit" in feats
    assert "0:tam:9" in feats
    assert "BOS" in feats and "EOS" in feats
    assert "0:123456789" in feats


def test_token2features_com_pontuacao_longa():
    sent = ["!!!"]
    feats = token2features(sent, 0)
    assert "0:is_punct" in feats
    assert "0:!" in feats
    assert "BOS" in feats and "EOS" in feats


def test_token2features_token_vazio():
    sent = [""]
    feats = token2features(sent, 0)
    assert "0:is_unknown" in feats
    assert "BOS" in feats
    assert "EOS" in feats
    assert "0:tam:0" in feats
    assert "0:is_alpha" not in feats


def test_token2features_token_desconhecido():
    sent = ["😀"]
    feats = token2features(sent, 0)
    assert "0:is_unknown" in feats
    assert "0:😀" not in feats
    assert "0:is_alpha" not in feats
    assert "BOS" in feats and "EOS" in feats


def test_token2features_token_com_acentos():
    sent = ["Árvore"]
    feats = token2features(sent, 0)
    assert "0:ARVORE" in feats
    assert "0:is_alpha" in feats
    assert "0:tam:6" in feats
    assert "BOS" in feats and "EOS" in feats
    assert "bias" in feats


# ----------------------------
# tokens2features
# ----------------------------
def test_tokens2features_lista_basica():
    toks = ["Rua", "das"]
    feats = tokens2features(toks)
    assert isinstance(feats, list)
    assert isinstance(feats[0], dict)
    assert "0:RUA" in feats[0]
    assert "0:DAS" in feats[1]


def test_tokens2features_contem_bias_em_todos():
    toks = ["A", "B", "C"]
    feats = tokens2features(toks)
    assert all("bias" in f for f in feats)


def test_tokens2features_sem_duplicatas():
    feats = tokens2features(["Rua", ",", "das", "Flores", "123"])
    for item in feats:
        assert len(item) == len(set(item))
