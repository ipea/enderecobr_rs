# Stub de tipos da extensão compilada em Rust. As docstrings públicas ficam em
# `src/*.rs` (é de lá que `help()` as lê); aqui ficam só as assinaturas, usadas
# por verificadores estáticos, IDEs e pelo mkdocstrings.

from collections.abc import Iterable
from pathlib import Path

def normalizar(valor: str) -> str: ...

def padronizar_logradouros(valor: str) -> str: ...

def padronizar_numeros(valor: str) -> str: ...

def padronizar_numeros_para_int(valor: str) -> int | None: ...

def padronizar_numeros_para_string(valor: float) -> str: ...

def padronizar_complementos(valor: str) -> str: ...

def padronizar_bairros(valor: str) -> str: ...

def padronizar_municipios(valor: str) -> str: ...

def is_dado_faltante(valor: str) -> bool: ...

def zerar_dado_faltante(valor: str) -> str: ...

def padronizar_estados_para_nome(valor: str) -> str: ...

def padronizar_estados_para_codigo(valor: str) -> str: ...

def padronizar_estados_para_sigla(valor: str) -> str: ...

def padronizar_tipo_logradouro(valor: str) -> str: ...

def padronizar_cep(valor: str) -> str: ...

def padronizar_cep_numerico(valor: int) -> str: ...

def padronizar_cep_leniente(valor: str) -> str: ...

class Padronizador:

    def __init__(self) -> None: ...

    def adicionar_substituicoes(self, pares: Iterable[Iterable[None | str]]) -> None: ...

    def padronizar(self, valor: str) -> str: ...

    def obter_substituicoes(self) -> list[tuple[str, str, None | str]]: ...

    def adicionar(self, regex: str, substituicao: str) -> None: ...

    def adicionar_com_ignorar(
        self, regex: str, substituicao: str, regex_ignorar: str
    ) -> None: ...

    def adicionar_vetores(
        self,
        regexes: Iterable[str],
        substituicoes: Iterable[str],
        regex_ignorar: Iterable[None | str],
    ) -> None: ...

    def preparar(self) -> None: ...

    def obter_vetores(self) -> tuple[list[str], list[str], list[None | str]]: ...

class IdentificadorPadroes:

    def __init__(self) -> None: ...

    def adicionar(self, regexs: Iterable[str]) -> None: ...

    def identificar(self, valor: str) -> bool: ...

def obter_padronizador_logradouros() -> Padronizador: ...

def obter_padronizador_numeros() -> Padronizador: ...

def obter_padronizador_bairros() -> Padronizador: ...

def obter_padronizador_complementos() -> Padronizador: ...

def obter_padronizador_tipos_logradouros() -> Padronizador: ...

def obter_padronizador_municipios() -> Padronizador: ...

def obter_padronizador_metaphone() -> Padronizador: ...

def obter_identificador_dado_faltante() -> IdentificadorPadroes: ...

def metaphone(valor: str) -> str: ...

def padronizar_numeros_por_extenso(valor: str) -> str: ...

def padronizar_numero_romano_por_extenso(valor: str) -> str: ...

def numero_por_extenso(n: int) -> str: ...

def romano_para_inteiro(valor: str) -> int: ...

class TipoSegmento:

    Logradouro: TipoSegmento
    LogradouroInterno: TipoSegmento
    Numero: TipoSegmento
    ModificadorNumero: TipoSegmento
    Complemento: TipoSegmento
    Empreendimento: TipoSegmento
    Parcela: TipoSegmento
    QuilometragemVia: TipoSegmento
    Referencia: TipoSegmento
    PontoReferencia: TipoSegmento
    Denominacao: TipoSegmento
    Localidade: TipoSegmento
    NucleoRural: TipoSegmento
    RecursoNatural: TipoSegmento
    Cep: TipoSegmento
    Municipio: TipoSegmento
    Uf: TipoSegmento
    Cadastro: TipoSegmento
    Ruido: TipoSegmento
    Outro: TipoSegmento

    @staticmethod
    def todos() -> list[TipoSegmento]: ...

class SegmentoEndereco:

    def __init__(self, valor: str, tipo: TipoSegmento) -> None: ...

    valor: str
    tipo: TipoSegmento

class EnderecoSegmentado:

    segmentos: list[SegmentoEndereco]

    def como_json(self) -> str: ...

class Endereco:

    logradouro: str | None
    numero: str | None
    complemento: str | None
    localidade: str | None
    cep: str | None

    def __init__(
        self,
        logradouro: str | None = None,
        numero: str | None = None,
        complemento: str | None = None,
        localidade: str | None = None,
        cep: str | None = None,
    ) -> None: ...

    def formatar(self) -> str: ...

    def padronizar(self) -> None: ...

    def endereco_padronizado(self) -> Endereco: ...

    def como_json(self) -> str: ...

class SeparadorEndereco:

    def __init__(self) -> None: ...

    @staticmethod
    def carregar(caminho: str | Path) -> SeparadorEndereco: ...

    def carregar_modelo(self, caminho: str | Path) -> None: ...

    def segmentar(self, texto: str) -> EnderecoSegmentado: ...

    def segmentar_enderecos(self, textos: Iterable[str]) -> list[EnderecoSegmentado]: ...

def obter_caminho_modelo(path_modelo: str | Path | None = None) -> Path: ...

def obter_modelo(path_modelo: str | Path | None = None) -> Path: ...

def segmentar_endereco(endereco: str) -> EnderecoSegmentado: ...

def segmentar_enderecos(enderecos: Iterable[str]) -> list[EnderecoSegmentado]: ...

def estruturar_endereco(endereco: str, padronizar: bool = True) -> Endereco: ...

# Constantes do modelo padrão. As descrições ficam em `__init__.py`, que é onde
# elas conseguem chegar ao mkdocstrings.

MODEL_DOWNLOAD_PATH: str

NOME_ARQUIVO_MODELO: str

NOME_DIRETORIO_CACHE: str

VERSAO_MODELO: str

VAR_AMBIENTE_MODELO: str

VAR_AMBIENTE_SEM_DOWNLOAD: str
