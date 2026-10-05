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
        "- `responder`: submete o resultado final. Sempre use esta ferramenta para responder.",
        "- `consulta_sql`: consulta o CNEFE no DuckDB. Limite por município e/ou uf, use sempre LIMIT e evite SELECT *.",
    ]
    if SEARX_URL:
        ferramentas.append("- `buscar`: realiza uma busca em vários motores de busca.")
    ferramentas.append(
        "- `acessar_url`: acessa uma URL e retorna o conteúdo em markdown (markitdown)."
    )
    secao_ferramentas = "\n".join(ferramentas)

    return f"""Você segmenta endereços brasileiros brutos em campos rotulados, para gerar dados de treino de um modelo de CRF.

## Regras gerais

1. Verbatim: cada `valor` é um trecho copiado exatamente como está no endereço bruto. Não normalize, não expanda abreviações, não corrija erros de digitação, não altere caixa nem acentos.
2. Use apenas o texto do endereço bruto como fonte dos `valor`. As "Informações extras" existem só para orientar o uso de ferramentas — o modelo treinado NUNCA as verá, então qualquer valor que não esteja verbatim no endereço será rejeitado. Não valide nem enriqueça: se um campo não aparece, não o crie; se você não conhece o endereço, responda mesmo assim.
3. Ordene os segmentos na ordem em que aparecem no texto.
4. Não rotule conectivos, conjunções e preposições: eles separam unidades e, portanto, viram corte entre segmentos.
5. Um segmento por referente. Tudo que aponta para o MESMO referente fica num único segmento, mesmo com vários tokens (ex.: "QD 34 LOTE 17", "GLEBA 10 AREA II LT 02 QD B", "Lotes 023/024/025 QD 34"). Unidades distintas — cada uma com seu próprio token — viram segmentos separados, e o conectivo entre elas não é rotulado (ex.: "AP 701 E VG 17" → dois `complemento`). Listas e intervalos com token ou separador compartilhado ficam num único segmento, com os separadores internos (/, -, ,) DENTRO do segmento (ex.: "Lotes 1-5", "10-20").
6. Trechos que remetem a outro endereço ou local são `referencia` (ex.: "ESQUINA COM", "EM FRENTE AO", "DESM DO"). O número dentro de uma referência pertence à referência, NÃO a `numero` — ou seja, `numero` do endereço principal é único.
7. `quilometragem_via` é a cota na própria via — o número É a posição ao longo dela ("KM 304", "BR-307 KM 304"). Um afastamento mede a separação de um marco ("200m da CE-040", "+ 6,6KM") e, por remeter a outro ponto, integra a `referencia`.
8. Município, UF, `localidade` e CEP, quando aparecem no próprio endereço, são rotulados normalmente — as "Informações extras" NUNCA populam segmentos. Um tipo de logradouro solto, sem nome associado (ex.: "A", "PR", "AC"), NÃO é `logradouro`: use `descricao_area`, `referencia` ou `outros` conforme o caso.

## Tabela de rótulos

| tipo | marcar | exemplo |
|---|---|---|
| logradouro | tipo + título + nome da via, verbatim; absorve rodovia | "R ALCIDES CARNEIRO LEAL", "AV OCEANICA", "ROD BR-116" |
| logradouro_interno | via/área interna a um empreendimento (não é logradouro oficial do município) | "RUA PROJETADA GH", "Rua 7 do Condomínio X" |
| numero | número do imóvel, incluindo ausência de número | "71", "S/N", "SN", "S/Nº" |
| modificador_numero | sufixo/marco colado ao número | "A", "504-B1", "POSTE" |
| complemento | unidade interna do imóvel, com tipo e valor juntos | "APTO 104", "BL 4", "SALA 306B", "VG 17" |
| empreendimento | nome de desenvolvimento: edifício, condomínio, conjunto, residencial, loteamento | "ED MANAGUA", "CONJ RES NICARAGUA", "COND PALM VILLAGE", "LOT JARDIM PIAI" |
| parcela | identificador cadastral do terreno. Hierarquia: gleba ⊃ (loteamento/desmembramento) ⊃ quadra ⊃ lote; "área" é subdivisão | "GLEBA 10 AREA II LT 02 QD B", "QD 34 LOTE 17", "Lotes 023/024/025" |
| descricao_area | descrição textual de área/terreno/uso (inclusive medida) — não é identificador | "ÁREA DE TERRA SITUADA NO LUGAR DENOMINADO...", "VIVEIRO DE CAMARAO", "Mar territorial", "8.278,00 m²" |
| quilometragem_via | cota na própria via: o número é a posição AO LONGO dela | "KM 304", "BR-307 KM 304" |
| referencia | trecho que remete a outro endereço ou local, sem detalhar subtipo aqui | "ESQUINA COM AV BOA VIAGEM", "EM FRENTE AO N. 2380", "DESM DO LT 06" |
| denominacao | denominação atual ou anterior do logradouro/local | "atual Luís Tanure", "ANTIGA RUA B" |
| localidade | nome de localidade, bairro, distrito, povoado, lugar ou zona | "PINA", "BARRA DO BEBEDOURO", "ZONA RURAL" |
| cep | CEP | "50720-000" |
| municipio | município | "RECIFE" |
| uf | unidade federativa | "PE" |
| ruido | apenas tokens/marcadores sem valor (pontuação, separadores soltos, id/registro vazado, lat/lon embutida) | "V 000 000", "NBP 1045707-4", "-20.23°,-41.51°" |
| outros | trecho com conteúdo semântico que não cabe nos demais tipos; sempre comente o motivo e sugira um tipo novo | — |

Atenção a falsos amigos: `FRENTE`/`FUNDOS` são `complemento` (frente/fundos do lote). Já `FRENTE PARA` / `EM FRENTE A` introduzindo outro logradouro NÃO é complemento — faz parte da `referencia`. Ex.: em "Frente para Rua Rui Barbosa", "Frente para" não é `complemento`.

## Ferramentas

{secao_ferramentas}

Política de uso: casos simples → responda direto, SEM chamar ferramenta. Só use ferramenta quando o trecho for ambíguo (ex.: município ou empreendimento desconhecido). Não chame ferramenta só para extrair trechos óbvios.

## Comentário

- `comentario` serve apenas para: (a) o que a busca ou a consulta SQL revelou; (b) dúvida real de rótulo. Máximo ~2 frases; não explique o óbvio.
- Sempre que usar `outros`, comente o motivo e sugira um tipo novo.

## Schema do CNEFE:

Base com ~110,6 milhões de linhas e ~106,4 milhões de endereços únicos (code_address). Cada linha é uma espécie presente no endereço (domicílio, estabelecimento etc.), logo um mesmo endereço aparece em várias linhas.

- Todo o texto está em MAIÚSCULAS e SEM ACENTOS.
- Texto vazio é '' (não NULL) e números ausentes são 0 (não NULL).
- Endereço sem número: num_adress = 0 com dsc_modificador = 'SN' (26 milhões de linhas). Quando dsc_modificador = 'KM', num_adress é a quilometragem (rodovias/estradas). O modificador também guarda sufixos de número (A, B, CASA 2...) e marcos (POSTE, SUCAM): é texto livre com ~157 mil valores distintos.
- NÃO existe coluna de bairro. desc_localidade é a localidade (sede de distrito, povoado, 'ZONA RURAL', 'CENTRO', até nomes de BRs), não um bairro.
- nom_tipo_seglogr tem 390 valores distintos. Mais comuns: RUA (73 mi), AVENIDA, ESTRADA, TRAVESSA, RODOVIA, FAZENDA, SITIO, EDF, POVOADO, ALAMEDA, BECO. Tipos rurais típicos: CORREGO, RAMAL, LINHA, COMUNIDADE, IGARAPE, ASSENTAMENTO, VIELA.
- nom_titulo_seglogr é vazio em 86% das linhas; quando preenchido é o título do logradouro (SAO, DOUTOR, SANTA, PADRE, CORONEL, PRESIDENTE...), separado do nome.
- nom_seglogr tem ~1,28 milhão de valores distintos e pode ser literalmente 'SEM DENOMINACAO' (1,2 milhão de linhas).
- Complementos vêm em pares nom_comp_elemN/val_comp_elemN (N=1 a 5; 1 e 2 são comuns, 3+ é raro). nom é a categoria (CASA, APARTAMENTO, BLOCO, QUADRA, FUNDOS, FRENTE, TERREO, ANDAR, LOTE, LOJA, TORRE, EDIFICIO, CONJUNTO...) e val é o valor, frequentemente vazio no elem1.
- cod_especie: 1=domicílio particular (82% das linhas), 3=estabelecimento agropecuário, 6=estabelecimento de outras finalidades, 7=edificação em construção. dsc_estabelecimento é o nome do estabelecimento (BAR, IGREJA, 'VAGO', 'SEM NOME'...), não do logradouro.
- code_muni é o código IBGE de 7 dígitos.

Procure limitar por municipio e/ou uf suas consultas, além de usar sempre um LIMIT e evitar SELECT *.

### Tabela 'cnefe':

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

### Tabela 'municipio':

column_name|column_type
-------------
cod_ibge|BIGINT
municipio|VARCHAR
uf|VARCHAR

### Tabela de refência de Estados (não está no banco):

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

# Funções úteis DuckDB

concat(value, ...) ou concat_ws(separator, string, ...) - Nulos são ignorados
ends_with(string, search_string) ou starts_with(string, search_string)
contains(string, search_string)
lower(string) ou upper()
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
    return f"""Informações extras (contexto apenas; NÃO servem para popular segmentos):
{extras}

Endereço bruto:
{endereco}

Você tem {n_rodadas} rodadas.
"""


def criar_ferramentas():
    tools = []

    tools.append(
        {
            "type": "function",
            "function": {
                "name": "responder",
                "description": "Dá a resposta final da solicitação",
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
                "name": "acessar_url",
                "description": "Acessa a URL solicitada e retorna o resultado usando a lib markitdown",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "url": {
                            "type": "string",
                            "description": "URL desejada",
                        },
                    },
                    "required": ["valor"],
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
                "name": "consulta_sql",
                "description": "Realiza uma consulta SQL usando o DuckDB em cima do CNEFE.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "sql": {
                            "type": "string",
                            "description": "SQL a ser executado",
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
                    "name": "buscar",
                    "description": "Realizar uma busca em vários motores de busca.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "Query de busca",
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


def buscar(query: str):
    if not SEARX_URL:
        return "A variável SEARX_URL não foi definida, a busca web não está disponível."

    params = {"q": query, "format": "json"}
    try:
        res = requests.get(SEARX_URL, params=params, timeout=30)
        resposta_bruta = res.json()
    except Exception as e:
        return f"Ocorreu um erro ao buscar por '{query}': {e!s}"

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


def acessar_url(url: str):
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
        return f"Ocorreu um erro ao acessar '{url}': {e!s}"


def consulta_sql(sql: str):
    try:
        consulta = conn.execute(sql)
        colunas = [str(col[0]) for col in consulta.description]
        resultado = consulta.fetchall()
    except Exception as e:
        return f"Ocorreu um erro ao realizar a consulta: {e!s}"

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
        case "buscar":
            return buscar(call.argumentos.get("query"))
        case "consulta_sql":
            return consulta_sql(call.argumentos.get("sql"))
        case "acessar_url":
            return acessar_url(call.argumentos.get("url"))

    return f"Ferramenta {call.nome} solicitada não existe"


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
                f"Não foi possível localizar o {i + 1}º segmento: {seg.valor} ({seg.tipo}) "
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
            "temperature": 0.6,
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
                        "content": f"Ocorreu um erro ao validar sua segmentação. Corrija e submeta novamente.\n{erro}",
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
                    "content": f"Iteração {i + 1} de {n_iter}",
                }
            )

        if i == n_iter - 1:
            print("ÚLTIMA ITERACAO")
            messages.append(
                {
                    "role": "user",
                    "content": "Última iteração - Dê sua resposta agora ou se abstenha",
                }
            )

    print(json.dumps(resposta_bruta, indent=4))


react_loop()
