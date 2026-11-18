"""Pagina standalone (HTML) com o CRF lendo exemplos reais do dataset.

Sem `modelo`, os exemplos saem do fold 0 da validacao cruzada, entao o modelo que
os previu nunca os viu — e a mesma regua do `crf avaliar --kfold 3`. Com
`modelo`, usa o tagger informado sobre o recorte de teste que o `crf treinar`
gravou no banco. A escolha e por diversidade de estrutura (rural, parcelamento,
referencia, erro...), nao por acerto: a pagina mostra o resultado como ele e.
"""

from __future__ import annotations

import json
import webbrowser
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import sklearn_crfsuite
import typer

from crf_endereco.config import CAMINHO_DATASET, DIR_DADOS
from crf_endereco.dataset import (
    abrir_banco,
    carregar_anotados,
    ler_recorte,
    segmentos_de,
)
from crf_endereco.estruturacao import estruturar_segmentos, formatar, padronizar
from crf_endereco.features import ExtratorFeature, tokenize, tokenize_com_offsets
from crf_endereco.modelo.crf import (
    SEMENTE_SPLIT,
    Exemplos,
    _indices_folds,
    _novo_crf,
    carregar_exemplos,
    montar_segmentos,
    nome_do_modelo,
)
from crf_endereco.rotulos import alinhamento
from crf_endereco.ui import console

CAMINHO_TEMPLATE = Path(__file__).parent / "exemplo.html"
DIR_SAIDA = DIR_DADOS / "visualizacoes"
CAMINHO_MODELO_OOF = DIR_DADOS / "modelos" / "tagger_oof_fold0.crf"
CAMINHO_META = CAMINHO_MODELO_OOF.with_suffix(".json")
FOLDS = 3
ALVO_PADRAO = 50

# Comeco tipico de endereco: usado so para abrir cada secao com um exemplo
# legivel, nao para filtrar nada.
CABECAS = frozenset({
    "RUA", "R", "AV", "AVE", "AVENIDA", "AL", "TRAV", "TV", "EST", "ROD", "PC", "PCA",
    "PRACA", "JD", "JARDIM", "LOTE", "LT", "QD", "QUADRA", "FAZ", "FAZENDA", "SIT",
    "SITIO", "GLB", "GLEBA", "CH", "VL", "VILA", "RES", "CONJ", "CONJUNTO", "POV",
    "POVOADO", "LAG", "LAGO", "SERRA", "MARGEM", "KM", "BR", "ST", "SETOR",
})

# Copia das cores de `crf_endereco.ui.CORES_TIPO` em hex (o HTML nao tem rich).
CORES = {
    "logradouro": "#22d3ee",
    "numero": "#f472b6",
    "complemento": "#facc15",
    "parcela": "#4ade80",
    "empreendimento": "#60a5fa",
    "localidade": "#3b82f6",
    "nucleo_rural": "#67e8f9",
    "recurso_natural": "#86efac",
    "referencia": "#e879f9",
    "ponto_referencia": "#fde047",
    "denominacao": "#f87171",
    "quilometragem_via": "#ff8a3d",
    "cep": "#ef4444",
    "municipio": "#a78bfa",
    "uf": "#c4b5fd",
    "cadastro": "#c084fc",
    "ruido": "#7b8794",
    "outros": "#8b9aa5",
    "fora": "#5b6874",
    "__outro": "#94a3b8",
}

# Uma linha por tipo de trecho, na ordem em que o anotador le a ontologia.
SIGNIFICADO = {
    "logradouro": "via: rua, avenida, rodovia, estrada",
    "numero": "numero do imovel",
    "complemento": "apto, bloco, casa, fundos",
    "parcela": "quadra, lote, gleba, unidade",
    "empreendimento": "nome proprio do predio, condominio ou estabelecimento",
    "localidade": "bairro, distrito, povoado",
    "nucleo_rural": "nucleo rural: fazenda, sitio, chacara",
    "recurso_natural": "rio, serra, lago, parque",
    "referencia": "marcador de referencia (proximo a, atras de)",
    "ponto_referencia": "o ponto de referencia em si",
    "denominacao": "marcador de nome antigo ou atual",
    "quilometragem_via": "km dentro da rodovia",
    "cep": "codigo postal",
    "municipio": "nome do municipio",
    "uf": "sigla do estado",
    "cadastro": "codigo de cadastro (SIAFI, matricula)",
    "ruido": "rotulo vazado da base de origem, sem valor de endereco",
    "outros": "trecho sem tipo identificavel",
}

# (nome da secao, quantos, quando vale a pena mostrar)
CATEGORIAS: list[tuple[str, int, Callable[[dict[str, Any]], bool]]] = [
    ("Logradouro e numero", 7, lambda c: set(c["tipos"]) == {"logradouro", "numero"}),
    ("Com bairro, municipio e CEP", 6,
     lambda c: {"logradouro", "numero", "localidade"} <= set(c["tipos"])
     <= {"logradouro", "numero", "localidade", "cep", "municipio", "uf"}),
    ("Rural e recursos naturais", 6,
     lambda c: bool(set(c["tipos"]) & {"nucleo_rural", "recurso_natural"})),
    ("Parcelamento (quadra, lote, gleba)", 5, lambda c: "parcela" in c["tipos"]),
    ("Empreendimento", 4, lambda c: "empreendimento" in c["tipos"]),
    ("Complementos e blocos", 4, lambda c: c["n_complementos"] >= 1),
    ("Referencias e nomes antigos", 4,
     lambda c: bool(set(c["tipos"]) & {"referencia", "ponto_referencia", "denominacao"})),
    ("Rodovia e quilometragem", 2, lambda c: "quilometragem_via" in c["tipos"]),
    ("Ruido, cadastro e sobra", 1,
     lambda c: bool(set(c["tipos"]) & {"ruido", "outros", "cadastro"})),
    ("Enderecos longos", 2, lambda c: c["n_tokens"] >= 16),
]

SECAO_ERROS = "Erros do modelo"
SECAO_SOBRA = "Outros exemplos"


@dataclass(frozen=True)
class Alvo:
    """O que a pagina mostra: o modelo, os indices de teste e de onde saiu o teste."""

    crf: sklearn_crfsuite.CRF
    indices: list[int]
    procedencia: str


def gerar(
    modelo: Path | None = None,
    dataset: Path = CAMINHO_DATASET,
    alvo: int = ALVO_PADRAO,
    saida: Path | None = None,
    retreinar: bool = False,
    abrir: bool = False,
) -> Path:
    """Escreve o HTML e devolve o caminho (abre no navegador se `abrir`)."""
    exemplos = carregar_exemplos(dataset)
    linhas = carregar_linhas(dataset)
    if len(linhas) != len(exemplos.y):
        raise typer.BadParameter(
            f"o dataset mudou durante a leitura ({len(linhas)} linhas vs "
            f"{len(exemplos.y)} exemplos) — anotacao em andamento? rode de novo"
        )
    if saida is None:
        saida = DIR_SAIDA / (
            "exemplos.html" if modelo is None else f"exemplos_{modelo.stem}.html"
        )

    escolhido = _preparar(exemplos, modelo, dataset, retreinar)
    extrator = ExtratorFeature()
    pesos = cast(dict[tuple[str, str], float], escolhido.crf.state_features_ or {})

    acertos_token = total_token = 0
    acertos_endereco = 0
    candidatos: list[dict[str, Any]] = []
    for indice in escolhido.indices:
        linha = linhas[indice]
        x = extrator.tokens2features(linha["tokens"])
        tags = [str(tag) for tag in escolhido.crf.predict_single(x)]
        marginais = escolhido.crf.predict_marginals_single(x)
        exemplo = descrever(indice, linha, linha["tokens"], tags, marginais, pesos, x)
        acertos_token += sum(1 for tk in exemplo["tokens"] if tk["gold"] == tk["pred"])
        total_token += len(exemplo["tokens"])
        acertos_endereco += int(exemplo["ok"])
        if len(linha["endereco"]) <= 150 and exemplo["n_tokens"] <= 26:
            candidatos.append(exemplo)

    escolhidos = escolher(candidatos, alvo)
    ordem = [c[0] for c in CATEGORIAS] + [SECAO_SOBRA, SECAO_ERROS]
    escolhidos.sort(
        key=lambda e: (
            ordem.index(e["categoria"]),
            e["tokens"][0]["t"].upper() not in CABECAS,
            e["endereco"],
        )
    )
    com_erro = sum(1 for e in escolhidos if not e["ok"])
    console.print(
        f"{len(escolhidos)} exemplos · {com_erro} com erro · "
        f"origens {dict(Counter(e['origem'] for e in escolhidos))}"
    )
    for categoria, quantos in Counter(e["categoria"] for e in escolhidos).items():
        console.print(f"  {categoria:38s} {quantos}")

    tipos = {
        label.split("_", 1)[1].lower() for labels in exemplos.y for label in labels if label != "O"
    }
    legenda = [[tipo, texto] for tipo, texto in SIGNIFICADO.items() if tipo in tipos]
    legenda.append(["fora", "nenhum tipo: o token nao entra em segmento algum"])
    dados: dict[str, Any] = {
        "resumo": (
            f"segmentação de endereços brasileiros · {len(exemplos.y):,}".replace(",", ".")
            + f" anotados · {len(tipos)} tipos de trecho · {escolhido.procedencia}"
        ),
        "metricas": {
            "token": f"{100 * acertos_token / total_token:.1f}%".replace(".", ","),
            "endereco": f"{100 * acertos_endereco / len(escolhido.indices):.1f}%".replace(
                ".", ","
            ),
        },
        "cores": CORES,
        "legenda": legenda,
        "exemplos": [
            {chave: valor for chave, valor in exemplo.items() if chave != "assinatura"}
            for exemplo in escolhidos
        ],
    }
    html = CAMINHO_TEMPLATE.read_text().replace(
        "__DADOS__", json.dumps(dados, ensure_ascii=False).replace("</", "<\\/")
    )
    saida.parent.mkdir(parents=True, exist_ok=True)
    _ = saida.write_text(html)
    console.print(
        f"token {dados['metricas']['token']} · endereco {dados['metricas']['endereco']} "
        f"em {len(escolhido.indices)} enderecos fora do treino ({escolhido.procedencia})"
    )
    console.print(f"escrito: {saida}")
    if abrir:
        _ = webbrowser.open(saida.resolve().as_uri())
    return saida


def _preparar(
    exemplos: Exemplos,
    modelo: Path | None,
    dataset: Path,
    retreinar: bool,
) -> Alvo:
    """Modelo e indices de teste: o `modelo` informado ou o fold 0 fora do treino."""
    if modelo is None:
        _, teste = _indices_folds(exemplos, FOLDS, SEMENTE_SPLIT, "origem")[0]
        return Alvo(
            crf=modelo_fold0(exemplos, teste, retreinar, dataset),
            indices=list(teste),
            procedencia="fold 0 da validação cruzada",
        )

    if not modelo.is_file():
        raise typer.BadParameter(f"tagger nao encontrado: {modelo}")
    conn = abrir_banco(dataset)
    try:
        recorte = ler_recorte(conn, nome_do_modelo(modelo))
    finally:
        conn.close()
    indices = [i for i, hash_ in enumerate(exemplos.hashes) if hash_ in recorte["teste"]]
    if not indices:
        raise typer.BadParameter(
            f"{modelo.name} nao tem recorte de teste no banco: treine com `crf treinar`"
        )
    return Alvo(
        crf=sklearn_crfsuite.CRF(model_filename=str(modelo)),
        indices=indices,
        procedencia=f"recorte de teste de {modelo.stem}",
    )


def carregar_linhas(dataset: Path = CAMINHO_DATASET) -> list[dict[str, Any]]:
    """Dataset utilizavel na mesma ordem de `carregar_exemplos` (indice a indice)."""
    linhas: list[dict[str, Any]] = []
    for exemplo in carregar_anotados(dataset):
        segmentos = segmentos_de(exemplo)
        tokens, labels, residuo = alinhamento(exemplo.endereco, segmentos, tokenize)
        if residuo or all(label == "O" for label in labels):
            continue
        linhas.append(
            {
                "endereco": exemplo.endereco,
                "origem": exemplo.origem,
                "uf": exemplo.uf,
                "municipio": exemplo.municipio,
                "tokens": tokens,
                "labels": labels,
            }
        )
    return linhas


def impressao_digital(dataset: Path = CAMINHO_DATASET) -> str:
    """Identidade do dataset no disco, incluindo o WAL.

    O banco roda em WAL: as escritas ficam no `-wal` e o mtime do arquivo
    principal nao muda, entao olhar so para ele deixaria passar anotacao nova.
    """
    marcas = []
    for caminho in (dataset, dataset.with_name(dataset.name + "-wal")):
        if caminho.is_file():
            estado = caminho.stat()
            marcas.append(f"{caminho.name}:{estado.st_size}:{int(estado.st_mtime)}")
    return "|".join(marcas)


def cache_valido(total: int, dataset: Path = CAMINHO_DATASET) -> bool:
    """Se o modelo em disco foi treinado neste recorte.

    O mtime tem granularidade de 1 segundo: anotacao gravada no mesmo segundo do
    `stat` passaria batido e o fold mudaria com o modelo velho, o que vaza
    exemplos de treino para o teste. Por isso a contagem de exemplos entra na
    chave junto com a impressao digital.
    """
    if not (CAMINHO_MODELO_OOF.is_file() and CAMINHO_META.is_file()):
        return False
    try:
        gravado = json.loads(CAMINHO_META.read_text())
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(gravado, dict):
        return False
    return (
        gravado.get("dataset") == impressao_digital(dataset)
        and gravado.get("n") == total
        and gravado.get("folds") == FOLDS
    )


def modelo_fold0(
    exemplos: Exemplos,
    teste: Sequence[int],
    retreinar: bool,
    dataset: Path = CAMINHO_DATASET,
) -> sklearn_crfsuite.CRF:
    """Modelo que exclui o fold 0 do treino (a pagina mostra so o fold 0).

    O cache so vale para o dataset que o gerou: o dataset cresce entre as
    execucoes e um modelo velho mediria um recorte que nao existe mais.
    """
    if not retreinar and cache_valido(len(exemplos.y), dataset):
        return sklearn_crfsuite.CRF(model_filename=str(CAMINHO_MODELO_OOF))

    treino = [i for i in range(len(exemplos.y)) if i not in set(teste)]
    console.print(f"treinando o fold 0 com {len(treino)} enderecos...")
    crf = _novo_crf(verboso=False, modelo=CAMINHO_MODELO_OOF)
    crf.fit([exemplos.x[i] for i in treino], [exemplos.y[i] for i in treino])
    _ = CAMINHO_META.write_text(
        json.dumps(
            {
                "dataset": impressao_digital(dataset),
                "folds": FOLDS,
                "n": len(exemplos.y),
                "treino": len(treino),
                "teste": len(teste),
            },
            indent=1,
        )
    )
    return crf


def descrever(
    indice: int,
    linha: dict[str, Any],
    tokens: list[str],
    tags: list[str],
    marginais: list[dict[str, float]],
    pesos: dict[tuple[str, str], float],
    x: list[dict[str, float]],
) -> dict[str, Any]:
    """Um exemplo pronto para o HTML: tokens, segmentos, campos e diferencas."""
    offsets = tokenize_com_offsets(linha["endereco"])
    erros = [
        {"i": i, "token": tok, "gold": gold, "pred": tag}
        for i, (tok, gold, tag) in enumerate(zip(tokens, linha["labels"], tags, strict=True))
        if gold != tag
    ]
    segmentos = montar_segmentos(linha["endereco"], offsets, tags)
    campos = padronizar(estruturar_segmentos(segmentos))

    detalhes = []
    for i, tok in enumerate(tokens):
        marginal = marginais[i]
        tag = tags[i]
        rival = max((par for par in marginal.items() if par[0] != tag), key=lambda par: par[1])
        ordenados = sorted(
            ((attr, pesos.get((attr, tag))) for attr in x[i]),
            key=lambda par: abs(par[1]) if par[1] is not None else -1.0,
            reverse=True,
        )
        detalhes.append(
            {
                "t": tok,
                "pred": tag,
                "gold": linha["labels"][i],
                "p": round(float(marginal.get(tag, 0.0)), 4),
                "rival": rival[0],
                "prival": round(float(rival[1]), 4),
                "punct": len(tok) == 1 and not tok.isalnum(),
                "top": [
                    [attr, None if peso is None else round(float(peso), 2)]
                    for attr, peso in ordenados[:8]
                ],
            }
        )

    return {
        "i": int(indice),
        "endereco": linha["endereco"],
        "origem": linha["origem"] or "?",
        "uf": linha["uf"],
        "municipio": linha["municipio"],
        "tokens": detalhes,
        "previsto": segmentos,
        "gold": montar_segmentos(linha["endereco"], offsets, linha["labels"]),
        "campos": [
            [campo, valor or "", campos[campo] or ""]
            for campo, valor in estruturar_segmentos(segmentos).items()
            if valor
        ],
        "final": formatar(campos),
        "erros": erros,
        "ok": not erros,
        "diferencas": len(erros),
        "tipos": sorted({tag.split("_", 1)[1].lower() for tag in linha["labels"] if tag != "O"}),
        "n_tokens": len(tokens),
        "n_complementos": sum(1 for tag in linha["labels"] if tag == "B_COMPLEMENTO"),
        "assinatura": tuple(sorted({(e["token"], e["gold"], e["pred"]) for e in erros})),
    }


def escolher(candidatos: list[dict[str, Any]], alvo: int) -> list[dict[str, Any]]:
    """Amostra diversa: cota por categoria, sem repetir origem nem endereco.

    Cada categoria prefere o que o modelo acertou (a maioria do dado real) e a
    secao de erros entra depois, com assinaturas de erro distintas — o objetivo e
    ilustrar o comportamento, nao colecionar falhas.
    """
    escolhidos: list[dict[str, Any]] = []
    vistos: set[str] = set()
    por_origem: Counter[str] = Counter()
    nesta: Counter[tuple[str, str]] = Counter()
    # As cotas de `CATEGORIAS` foram calibradas para `ALVO_PADRAO`: pedir mais
    # exemplos tem que engordar cada secao, nao so bater no teto delas.
    fator = alvo / ALVO_PADRAO
    assinaturas: set[tuple[tuple[str, str, str], ...]] = set()

    cota_erros = max(6, alvo // 5)

    def cabe(candidato: dict[str, Any], categoria: str, limite: int, teto: int) -> bool:
        return (
            len(escolhidos) < teto
            and candidato["endereco"] not in vistos
            and por_origem[candidato["origem"]] < 2 * limite
            and nesta[(categoria, candidato["origem"])] < 2
        )

    def pegar(candidato: dict[str, Any], categoria: str) -> None:
        candidato["categoria"] = categoria
        escolhidos.append(candidato)
        vistos.add(candidato["endereco"])
        por_origem[candidato["origem"]] += 1
        nesta[(categoria, candidato["origem"])] += 1

    for categoria, cota_base, vale in CATEGORIAS:
        cota = max(1, round(cota_base * fator))
        contagem = 0
        for candidato in candidatos:
            if contagem >= cota:
                break
            if not candidato["ok"] or not vale(candidato):
                continue
            if not cabe(candidato, categoria, cota, alvo - cota_erros):
                continue
            pegar(candidato, categoria)
            contagem += 1

    erros = 0
    for candidato in candidatos:
        if erros >= cota_erros:
            break
        assinatura = cast(tuple[tuple[str, str, str], ...], candidato["assinatura"])
        if candidato["ok"] or not 1 <= candidato["diferencas"] <= 3:
            continue
        if assinatura in assinaturas or not cabe(candidato, SECAO_ERROS, cota_erros, alvo):
            continue
        assinaturas.add(assinatura)
        pegar(candidato, SECAO_ERROS)
        erros += 1

    # As categorias estruturais acabam antes da cota no recorte de teste (poucas
    # ruas com numero puro, quase nenhuma rodovia): completa com o que sobrou,
    # sempre puxando a origem menos representada na pagina.
    resto = [c for c in candidatos if c["ok"] and c["endereco"] not in vistos]
    while resto and len(escolhidos) < alvo:
        candidato = min(resto, key=lambda c: (por_origem[c["origem"]], c["n_tokens"]))
        resto.remove(candidato)
        pegar(candidato, SECAO_SOBRA)
    return escolhidos
