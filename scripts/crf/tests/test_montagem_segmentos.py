from crf_endereco.features import tokenize_com_offsets
from crf_endereco.modelos.inferencia import montar_segmentos


def segmentar_tokens(frase: str, tags: list[str]) -> list[dict[str, str]]:
    return montar_segmentos(frase, tokenize_com_offsets(frase), tags)


def test_montar_segmentos_preserva_separador_original():
    # "S/N" e "310A" não têm espaço antes do "N"/"A" no texto bruto: o Rust
    # mantém verbatim e aqui tem que ser igual.
    assert segmentar_tokens(
        "R ABAETE S/N LOTE 10",
        [
            "B_logradouro",
            "I_logradouro",
            "B_numero",
            "I_numero",
            "I_numero",
            "B_parcela",
            "I_parcela",
        ],
    ) == [
        {"tipo": "logradouro", "valor": "R ABAETE"},
        {"tipo": "numero", "valor": "S/N"},
        {"tipo": "parcela", "valor": "LOTE 10"},
    ]

    assert segmentar_tokens(
        "AV SAGITARIO 138 CJ 310A",
        [
            "B_logradouro",
            "I_logradouro",
            "B_numero",
            "B_complemento",
            "I_complemento",
            "I_complemento",
        ],
    ) == [
        {"tipo": "logradouro", "valor": "AV SAGITARIO"},
        {"tipo": "numero", "valor": "138"},
        {"tipo": "complemento", "valor": "CJ 310A"},
    ]


def test_montar_segmentos_insere_espaco_quando_havia_espaco():
    assert segmentar_tokens(
        "RUA DAS FLORES",
        ["B_logradouro", "I_logradouro", "I_logradouro"],
    ) == [{"tipo": "logradouro", "valor": "RUA DAS FLORES"}]


def test_montar_segmentos_ignora_o_e_i_sem_b():
    assert (
        segmentar_tokens(
            "RUA 123",
            ["O", "O"],
        )
        == []
    )

    assert segmentar_tokens(
        "RUA 123",
        ["I_logradouro", "B_numero"],
    ) == [{"tipo": "numero", "valor": "123"}]


def test_montar_segmentos_i_de_tipo_diferente_e_ignorado():
    assert segmentar_tokens(
        "RUA 123",
        ["B_logradouro", "I_numero"],
    ) == [{"tipo": "logradouro", "valor": "RUA"}]
