#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["markitdown[pdf,docx,xls,xlsx]", "requests", "duckdb"]
# ///

import json
import os
import tempfile
from dataclasses import dataclass
from pprint import pprint
from typing import Any

import duckdb
import markitdown
import requests

API_KEY = os.environ.get("API_KEY")
API_URL = os.environ.get("API_URL")
API_MODEL = os.environ.get("API_MODEL")
SEARX_URL = os.environ.get("SEARX_URL")
CNEFE_PATH = os.environ.get("CNEFE_PATH")
MUNICIPIOS_PATH = "../../src/data/municipios.csv"

md = markitdown.MarkItDown()

if not API_KEY or not API_MODEL or not API_URL:
    raise Exception(
        "As variáveis de ambiente API_MODEL, API_MODEL, API_URL devem ser fornecidas."
    )

if not CNEFE_PATH:
    raise Exception("A variável de ambiente CNEFE_PATH deve ser fornecida.")

if not SEARX_URL:
    print(
        "Atenção: A variável SEARX_URL não foi definida, a ferramenta de busca web não estará disponível."
    )


def renderizar_prompt_sistema() -> str:
    ferramentas = [
        "- `responder`: submit the final result. Always use this tool to answer.",
        "- `sql_query`: query CNEFE in DuckDB. Restrict by município and/or uf, always use LIMIT and avoid SELECT *.",
    ]
    if SEARX_URL:
        ferramentas.append("- `search`: search across several search engines.")
    ferramentas.append(
        "- `fetch_url`: fetch a URL and return its content as markdown (markitdown)."
    )
    secao_ferramentas = "\n".join(ferramentas)

    return f"""You segment raw Brazilian addresses into labeled fields to generate training data for a CRF model.

## General rules

1. Verbatim: every `valor` is a snippet copied exactly as it appears in the raw address. Do not normalize, expand abbreviations, fix typos, or change case/accents.
2. Use only the raw address text as the source of `valor`. The "Extra info" exists only to guide tool use — the trained model will NEVER see it, so any value not verbatim in the address will be rejected. Do not validate or enrich: if a field is absent, do not create it; if you don't know the address, answer anyway.
3. Order segments as they appear in the text.
4. Do not label connectives, conjunctions or prepositions: they separate units and therefore act as a cut between segments.
5. One segment per referent. Everything pointing to the SAME referent stays in a single segment, even with several tokens (e.g.: "QD 34 LOTE 17", "GLEBA 10 AREA II LT 02 QD B", "Lotes 023/024/025 QD 34"). Distinct units — each with its own token — become separate segments, and the connective between them is not labeled (e.g.: "AP 701 E VG 17" → two `complemento`). Lists and ranges with a shared token or separator stay in a single segment, with internal separators (/, -, ,) INSIDE the segment (e.g.: "Lotes 1-5", "10-20").
6. Snippets that point to another address or place are `referencia` (e.g.: "ESQUINA COM", "EM FRENTE AO", "DESM DO"). A number inside a reference belongs to the reference, NOT to `numero` — that is, `numero` of the main address is unique.
7. `quilometragem_via` is the route kilometer — the number IS the position along the road ("KM 304", "BR-307 KM 304"). An offset measures the distance from a landmark ("200m da CE-040", "+ 6,6KM") and, since it points to another place, belongs to `referencia`.
8. Município, UF, `localidade` and CEP, when present in the address itself, are labeled normally — the "Extra info" NEVER populates segments. A bare street-type token without an associated name (e.g.: "A", "PR", "AC") is NOT `logradouro`: use `descricao_area`, `referencia` or `outros` as appropriate.

## Label table

| tipo | what to mark | example |
|---|---|---|
| logradouro | street type + title + name, verbatim; absorbs rodovia | "R ALCIDES CARNEIRO LEAL", "AV OCEANICA", "ROD BR-116" |
| logradouro_interno | way/area internal to a development (not an official municipal street) | "RUA PROJETADA GH", "Rua 7 do Condomínio X" |
| numero | property number, including absence of a number | "71", "S/N", "SN", "S/Nº" |
| modificador_numero | suffix/marker attached to the number | "A", "504-B1", "POSTE" |
| complemento | internal unit of the property, type and value together | "APTO 104", "BL 4", "SALA 306B", "VG 17" |
| empreendimento | development name: building, condominium, conjunto, residencial, loteamento | "ED MANAGUA", "CONJ RES NICARAGUA", "COND PALM VILLAGE", "LOT JARDIM PIAI" |
| parcela | cadastral identifier of the land. Hierarchy: gleba ⊃ (loteamento/desmembramento) ⊃ quadra ⊃ lote; "área" is a subdivision | "GLEBA 10 AREA II LT 02 QD B", "QD 34 LOTE 17", "Lotes 023/024/025" |
| descricao_area | textual description of land/area/use (including measurement) — not an identifier | "ÁREA DE TERRA SITUADA NO LUGAR DENOMINADO...", "VIVEIRO DE CAMARAO", "Mar territorial", "8.278,00 m²" |
| quilometragem_via | route kilometer: the number is the position ALONG the road | "KM 304", "BR-307 KM 304" |
| referencia | snippet that points to another address or place; do not detail the subtype here | "ESQUINA COM AV BOA VIAGEM", "EM FRENTE AO N. 2380", "DESM DO LT 06" |
| denominacao | current or former name of the street/place | "atual Luís Tanure", "ANTIGA RUA B" |
| localidade | name of a locality, bairro, district, village, place or zone | "PINA", "BARRA DO BEBEDOURO", "ZONA RURAL" |
| cep | CEP | "50720-000" |
| municipio | município | "RECIFE" |
| uf | federal unit | "PE" |
| ruido | bare tokens/markers with no value (punctuation, loose separators, leaked record id, embedded lat/lon) | "V 000 000", "NBP 1045707-4", "-20.23°,-41.51°" |
| outros | meaningful content fitting no other type; always comment the reason and suggest a new type | — |

Watch out for false friends: `FRENTE`/`FUNDOS` are `complemento` (front/rear of the lot). But `FRENTE PARA` / `EM FRENTE A` introducing another street is NOT complemento — it is part of `referencia`. E.g.: in "Frente para Rua Rui Barbosa", "Frente para" is not `complemento`.

## Tools

{secao_ferramentas}

Usage policy: simple cases → answer directly, WITHOUT calling a tool. Only use a tool when the snippet is ambiguous (e.g. unknown município or development). Do not call a tool just to extract obvious snippets.

## Comment

- `comentario` is only for: (a) what the search or the SQL query revealed; (b) a real labeling doubt. Max ~2 sentences; do not explain the obvious.
- Whenever you use `outros`, comment the reason and suggest a new type.

## CNEFE schema:

Base with ~110.6 million rows and ~106.4 million unique addresses (code_address). Each row is a species present at the address (household, establishment, etc.), so the same address appears in several rows.

- All text is UPPERCASE and WITHOUT ACCENTS.
- Empty text is '' (not NULL) and missing numbers are 0 (not NULL).
- Address with no number: num_adress = 0 with dsc_modificador = 'SN' (26 million rows). When dsc_modificador = 'KM', num_adress is the kilometer (highways/roads). The modifier also holds number suffixes (A, B, CASA 2...) and markers (POSTE, SUCAM): it is free text with ~157 thousand distinct values.
- There is NO bairro column. desc_localidade is the locality (district seat, village, 'ZONA RURAL', 'CENTRO', even BR names), not a bairro.
- nom_tipo_seglogr has 390 distinct values. Most common: RUA (73 mi), AVENIDA, ESTRADA, TRAVESSA, RODOVIA, FAZENDA, SITIO, EDF, POVOADO, ALAMEDA, BECO. Typical rural types: CORREGO, RAMAL, LINHA, COMUNIDADE, IGARAPE, ASSENTAMENTO, VIELA.
- nom_titulo_seglogr is empty in 86% of rows; when filled it is the street title (SAO, DOUTOR, SANTA, PADRE, CORONEL, PRESIDENTE...), separate from the name.
- nom_seglogr has ~1.28 million distinct values and can be literally 'SEM DENOMINACAO' (1.2 million rows).
- Complements come in pairs nom_comp_elemN/val_comp_elemN (N=1 to 5; 1 and 2 are common, 3+ is rare). nom is the category (CASA, APARTAMENTO, BLOCO, QUADRA, FUNDOS, FRENTE, TERREO, ANDAR, LOTE, LOJA, TORRE, EDIFICIO, CONJUNTO...) and val is the value, often empty in elem1.
- cod_especie: 1=private household (82% of rows), 3=agricultural establishment, 6=establishment for other purposes, 7=building under construction. dsc_estabelecimento is the establishment name (BAR, IGREJA, 'VAGO', 'SEM NOME'...), not the street.
- code_muni is the 7-digit IBGE code.

Try to restrict your queries by municipio and/or uf, and always use a LIMIT and avoid SELECT *.

### Table 'cnefe':

column_name|column_type
-------------
code_address|INTEGER
code_state|INTEGER
code_muni|INTEGER
code_district|INTEGER
code_sub_district|BIGINT
code_sector|VARCHAR
num_quadra|INTEGER
num_face|INTEGER
cep|INTEGER
desc_localidade|VARCHAR
nom_tipo_seglogr|VARCHAR
nom_titulo_seglogr|VARCHAR
nom_seglogr|VARCHAR
num_adress|INTEGER
dsc_modificador|VARCHAR
nom_comp_elem1|VARCHAR
val_comp_elem1|VARCHAR
nom_comp_elem2|VARCHAR
val_comp_elem2|VARCHAR
nom_comp_elem3|VARCHAR
val_comp_elem3|VARCHAR
nom_comp_elem4|VARCHAR
val_comp_elem4|VARCHAR
nom_comp_elem5|VARCHAR
val_comp_elem5|VARCHAR
lat|DOUBLE
lon|DOUBLE
nv_geo_coord|INTEGER
cod_especie|INTEGER
dsc_estabelecimento|VARCHAR
cod_indicador_estab_endereco|INTEGER
cod_indicador_const_endereco|INTEGER
cod_indicador_finalidade_const|INTEGER
cod_tipo_especi|INTEGER

### Table 'municipio':

column_name|column_type
-------------
cod_ibge|BIGINT
municipio|VARCHAR
uf|VARCHAR

### Reference table of States (not in the database):

codigo|nome
-----
11|RONDONIA
12|ACRE
13|AMAZONAS
14|RORAIMA
15|PARA
16|AMAPA
17|TOCANTINS
21|MARANHAO
22|PIAUI
23|CEARA
24|RIO GRANDE DO NORTE
25|PARAIBA
26|PERNAMBUCO
27|ALAGOAS
28|SERGIPE
29|BAHIA
31|MINAS GERAIS
32|ESPIRITO SANTO
33|RIO DE JANEIRO
35|SAO PAULO
41|PARANA
42|SANTA CATARINA
43|RIO GRANDE DO SUL
50|MATO GROSSO DO SUL
51|MATO GROSSO
52|GOIAS
53|DISTRITO FEDERAL

# Useful DuckDB functions

concat(value, ...) or concat_ws(separator, string, ...) - NULLs are ignored
ends_with(string, search_string) or starts_with(string, search_string)
contains(string, search_string)
lower(string) or upper()
len(string)
strip_accents(string)
regexp_matches(string, regex[, options])

levenshtein(s1, s2)
damerau_levenshtein(s1, s2)
jaccard(s1, s2)
jaro_winkler_similarity(s1, s2[, score_cutoff])
jaro_similarity(s1, s2[, score_cutoff])


"""


def renderizar_prompt_usuario(endereco: str, extras: str, n_rodadas: int) -> str:
    return f"""Extra info (context only; it does NOT populate segments):
{extras}

Raw address:
{endereco}

You have {n_rodadas} rounds.
"""


def criar_ferramentas():
    tools = []

    tools.append(
        {
            "type": "function",
            "function": {
                "name": "responder",
                "description": "Submit the final answer to the request",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "segmentos": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "valor": {"type": "string"},
                                    "tipo": {
                                        "type": "string",
                                        "enum": [
                                            "logradouro",
                                            "logradouro_interno",
                                            "numero",
                                            "modificador_numero",
                                            "complemento",
                                            "empreendimento",
                                            "parcela",
                                            "descricao_area",
                                            "quilometragem_via",
                                            "referencia",
                                            "denominacao",
                                            "localidade",
                                            "cep",
                                            "municipio",
                                            "uf",
                                            "ruido",
                                            "outros",
                                        ],
                                    },
                                },
                                "required": ["valor", "tipo"],
                                "additionalProperties": False,
                            },
                            "minItems": 1,
                        },
                        "comentario": {
                            "type": "string",
                        },
                    },
                    "required": ["segmentos"],
                    "additionalProperties": False,
                },
                "strict": True,
            },
        }
    )

    tools.append(
        {
            "type": "function",
            "function": {
                "name": "fetch_url",
                "description": "Fetch the requested URL and return the result in markdown",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "url": {
                            "type": "string",
                            "description": "Requested URL",
                        },
                    },
                    "required": ["url"],
                    "additionalProperties": False,
                },
                "strict": True,
            },
        }
    )

    tools.append(
        {
            "type": "function",
            "function": {
                "name": "sql_query",
                "description": "Run a SQL query using DuckDB over CNEFE.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "sql": {
                            "type": "string",
                            "description": "SQL to execute",
                        },
                    },
                    "required": ["sql"],
                    "additionalProperties": False,
                },
                "strict": True,
            },
        }
    )

    if SEARX_URL:
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": "search",
                    "description": "Search across several search engines.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "Search query",
                            },
                        },
                        "required": ["query"],
                        "additionalProperties": False,
                    },
                    "strict": True,
                },
            }
        )
    return tools


def iniciar_duckbd():
    caminho_db = os.path.join(tempfile.gettempdir(), "cnefe-enderecobr.db")
    conn = duckdb.connect(caminho_db)
    conn.register("cnefe", conn.read_parquet(CNEFE_PATH))
    conn.register("municipio", conn.read_csv(MUNICIPIOS_PATH))

    return conn


conn = iniciar_duckbd()


def search(query: str):
    if not SEARX_URL:
        return "SEARX_URL is not set; web search is unavailable."

    params = {"q": query, "format": "json"}
    try:
        res = requests.get(SEARX_URL, params=params, timeout=30)
        resposta_bruta = res.json()
    except Exception as e:
        return f"An error occurred while searching for '{query}': {e!s}"

    resposta_final = []
    for result in resposta_bruta.get("results", []):
        titulo = result.get("title", "")
        conteudo = result.get("content", "")
        url = result.get("url", "")
        engines = result.get("engines", [])
        pubdate = result.get("pubdate", [])  # Data formatada

        atual = f"""# {titulo}
url: {url}
motores de busca: {", ".join(engines)}
data publicação: {pubdate}
conteúdo: {conteudo}

"""
        resposta_final.append(atual)

    return "\n".join(resposta_final)


def fetch_url(url: str):
    try:
        res = requests.get(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:156.0) Gecko/20100101 Firefox/156.0",
            },
            timeout=30,
        )
        return str(md.convert(res).markdown)
    except Exception as e:
        return f"An error occurred while fetching '{url}': {e!s}"


def sql_query(sql: str):
    try:
        consulta = conn.execute(sql)
        colunas = [str(col[0]) for col in consulta.description]
        resultado = consulta.fetchall()
    except Exception as e:
        return f"An error occurred while running the query: {e!s}"

    corpo_tabela = "\n".join(["|".join([str(e) for e in linha]) for linha in resultado])

    return f"""{"|".join(colunas)}
---------
{corpo_tabela}
"""


@dataclass()
class ToolCall:
    idx: str
    nome: str
    argumentos: Any


@dataclass()
class Segmento:
    valor: str
    tipo: str


@dataclass()
class RespostaFinal:
    segmentos: list[Segmento]
    comentario: str | None


@dataclass()
class RespostaModelo:
    resposta: str
    raciociono: str
    tool_calls: list[ToolCall]
    message_original: Any

    def obter_resposta_final(self):
        return next(iter([c for c in self.tool_calls if c.nome == "responder"]), None)


def estruturar_ferramentas(bruto):
    chamadas_ferramentas = bruto.get("tool_calls", [])
    resultado: list[ToolCall] = []
    for call in chamadas_ferramentas:
        idx = call.get("id", "")
        fun = call.get("function", {})
        nome: str = fun.get("name", "")
        args_bruto = fun.get("arguments")
        try:
            args = json.loads(args_bruto)
        except (json.JSONDecodeError, TypeError):
            continue

        resultado.append(ToolCall(idx, nome, args))
    return resultado


def estruturar_resposta_modelo(resposta_bruta) -> RespostaModelo:
    msg_modelo = resposta_bruta.get("choices", [{}])[0].get("message", {})

    resposta = msg_modelo.get("content")
    raciociono = msg_modelo.get("reasoning", "")
    calls = estruturar_ferramentas(msg_modelo)

    return RespostaModelo(resposta, raciociono, calls, msg_modelo)


def despachar_ferramenta(call: ToolCall):
    match call.nome:
        case "search":
            return search(call.argumentos.get("query"))
        case "sql_query":
            return sql_query(call.argumentos.get("sql"))
        case "fetch_url":
            return fetch_url(call.argumentos.get("url"))

    return f"Requested tool {call.nome} does not exist"


def processar_resultado_final(resposta: ToolCall) -> RespostaFinal:
    segmentos = resposta.argumentos.get("segmentos", [])
    comentario = resposta.argumentos.get("comentario")

    resposta_final = RespostaFinal(segmentos=[], comentario=comentario)

    for seg in segmentos:
        tipo = str(seg.get("tipo", ""))
        valor = str(seg.get("valor", ""))
        resposta_final.segmentos.append(Segmento(valor=valor, tipo=tipo))

    return resposta_final


def validar_resposta_final(
    endereco: str, resposta: RespostaFinal
) -> tuple[str, str | None]:
    ultima_pos = 0

    problemas: list[str] = []
    visualizacao_segmentos: list[str] = []

    for i, seg in enumerate(resposta.segmentos):
        posicao_segmento = endereco.find(seg.valor, ultima_pos)

        if posicao_segmento == -1:
            problemas.append(
                f"Could not locate segment #{i + 1}: {seg.valor} ({seg.tipo}) "
            )
            continue

        if posicao_segmento != ultima_pos:
            visualizacao_segmentos.append(endereco[ultima_pos:posicao_segmento])

        nova_posicao = posicao_segmento + len(seg.valor)

        visualizacao_segmentos.append(
            f"{endereco[posicao_segmento:nova_posicao]} [{seg.tipo}]"
        )

        ultima_pos = nova_posicao

    if ultima_pos != len(endereco):
        visualizacao_segmentos.append(endereco[ultima_pos:])

    problemas_str = None
    if len(problemas):
        problemas_str = "\n".join(problemas)

    vis = "\n".join(visualizacao_segmentos)
    return (vis, problemas_str)


def realizar_requisicao(messages):
    response = requests.post(
        f"{API_URL}/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": API_MODEL,
            "messages": messages,
            "tools": criar_ferramentas(),
            "temperature": 0.3,
        },
        timeout=300,
    )

    response.raise_for_status()
    data = response.json()
    return data


def react_loop(n_iter: int = 10, n_paciencia_erro: int = 2):
    # "FAZ ÁREA DE TERRA SITUADA NO LUGAR DENOMINADO BARRA DO BEBEDOURO 0 BARRA DO BEBEDOURO",
    # "R ALCIDES CARNEIRO LEAL 71 APTO 104 ED MANAGUA CONJ RES NICARAGUA",
    # "Municipio: Recife/PE\nBairro: PINA\nBanco de Dados: Imóveis da União",

    # endereco = "FAZ PIRA COMBOA DOS CAVALOS E OUTROS S/N VIVEIRO DE CAMARAO"
    # endereco = "AV OCEANICA 3009 ED. SOLARIUS - AP. 606 E VAGA DE GARAGEM"
    # endereco = "R C 64 QD VIII, LOTE 127, LOT NOSSA SENHORA PEN"
    # endereco = "ROD BR 307, KM 304 113 Lote 113, Conjunto Residencial Lobo D'Almada"
    # endereco = "R Antonio Gomes dos Santos s/n Dista 200m da CE-040, estrada que liga Tapera à Canoa"
    # endereco = "PR Mar territorial. Parque Aquícola Marinho Amontada 01. s/n Área E"
    # endereco = "A De 8.278,00 m² - Patio da Estação s/n Frente para Rua Rui Barbosa"
    # endereco = "AC SAI DO POV. CAPIM GROSSO VIRA A DIR. NO AÇÚDE PÚB. + 6,6KM V 000 000"
    # endereco = "AV BR-343 KM-08-LADO ESQUERDO SENT. PBA- LUIZ CORREIA S/N Km 08, próximo ao acesso ao aeroporto de Parnaíba"
    endereco = "FAZ FAZENDA LUAR DO YBICUHY - S/Nº PA SEPE TIARAJU III - BR 1581293 - SNATANA DO LIVRAMENTO/RS"
    endereco = "AV Presidente Dutra 1172 Com uma vaga de estacionamento"

    extras = "Municipio: Itaperuna/RJ\nBairro: Pres. Costa e Silva\nBanco de Dados: Imóveis da União"

    n_erros = n_paciencia_erro
    resposta_bruta = {}

    messages = [
        {
            "role": "system",
            "content": renderizar_prompt_sistema(),
        },
        {
            "role": "user",
            "content": renderizar_prompt_usuario(endereco, extras, n_iter),
        },
    ]

    for i in range(n_iter):
        print(f"Iteração #{i + 1}")

        resposta_bruta = realizar_requisicao(messages)
        resposta = estruturar_resposta_modelo(resposta_bruta)

        messages.append(resposta.message_original)

        print("========================")
        print(f"# Raciociono:\n{resposta.raciociono}")
        print("========================")
        print()

        if resposta.resposta:
            print(resposta.resposta)

        resposta_final = resposta.obter_resposta_final()

        if resposta_final:
            resultado_final = processar_resultado_final(resposta_final)
            vis, erro = validar_resposta_final(endereco, resultado_final)

            print()
            pprint(resultado_final)
            print("Visualizacao:")
            print(vis)
            print("-------------")
            if erro:
                print("Erro:", erro)
                messages.append(
                    {
                        "role": "user",
                        "content": f"An error occurred while validating your segmentation. Fix it and submit again.\n{erro}",
                    }
                )

                if n_erros == 0:
                    n_erros -= 1
                    i -= 1
                    continue

            else:
                break

        if not resposta_final:
            for c in resposta.tool_calls:
                pprint(c)
                resposta_ferramenta = despachar_ferramenta(c)
                print()
                print(resposta_ferramenta)

                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": c.idx,
                        "content": resposta_ferramenta,
                    }
                )

        if i == n_iter - 1:
            messages.append(
                {
                    "role": "user",
                    "content": f"Round {i + 1} of {n_iter}",
                }
            )

        if i == n_iter - 1:
            print("ÚLTIMA ITERACAO")
            messages.append(
                {
                    "role": "user",
                    "content": "Final round - Give your answer now or abstain",
                }
            )

    print(json.dumps(resposta_bruta, indent=4))


react_loop()
