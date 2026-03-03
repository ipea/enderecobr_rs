use std::sync::LazyLock;

use rustc_hash::FxHashMap;

use crate::{normalizar, Padronizador};

static PADRONIZADOR: LazyLock<Padronizador> = LazyLock::new(criar_padronizador);

static MUNICIPIOS_MAP: LazyLock<FxHashMap<String, String>> = LazyLock::new(criar_municipio_map);

pub fn criar_padronizador() -> Padronizador {
    let mut padronizador = Padronizador::default();

    padronizador
        .adicionar(r"\b0+(\d+)\b", "$1") // Remove zeros na frente
        .adicionar(r"\s{2,}", " ") // Remove espaços extra
        .adicionar("^MOJI MIRIM$", "MOGI MIRIM")
        .adicionar("^GRAO PARA$", "GRAO-PARA")
        .adicionar("^BIRITIBA-MIRIM$", "BIRITIBA MIRIM")
        .adicionar("^SAO LUIS DO PARAITINGA$", "SAO LUIZ DO PARAITINGA")
        .adicionar("^TRAJANO DE MORAIS$", "TRAJANO DE MORAES")
        .adicionar("^PARATI$", "PARATY")
        .adicionar("^LAGOA DO ITAENGA$", "LAGOA DE ITAENGA")
        .adicionar("^ELDORADO DOS CARAJAS$", "ELDORADO DO CARAJAS")
        .adicionar("^SANTANA DO LIVRAMENTO$", "SANT'ANA DO LIVRAMENTO")
        .adicionar("^BELEM DE SAO FRANCISCO$", "BELEM DO SAO FRANCISCO")
        .adicionar("^SANTO ANTONIO DO LEVERGER$", "SANTO ANTONIO DE LEVERGER")
        .adicionar("^POXOREO$", "POXOREU")
        .adicionar("^SAO THOME DAS LETRAS$", "SAO TOME DAS LETRAS")
        .adicionar("^OLHO-D'AGUA DO BORGES$", "OLHO D'AGUA DO BORGES")
        .adicionar("^ITAPAGE$", "ITAPAJE")
        .adicionar("^MUQUEM DE SAO FRANCISCO$", "MUQUEM DO SAO FRANCISCO")
        .adicionar("^DONA EUSEBIA$", "DONA EUZEBIA")
        .adicionar("^PASSA-VINTE$", "PASSA VINTE")
        .adicionar("^AMPARO DE SAO FRANCISCO$", "AMPARO DO SAO FRANCISCO")
        .adicionar("^BRASOPOLIS$", "BRAZOPOLIS")
        .adicionar("^SERIDO$", "SAO VICENTE DO SERIDO")
        .adicionar("^IGUARACI$", "IGUARACY")
        .adicionar("^AUGUSTO SEVERO$", "CAMPO GRANDE")
        .adicionar("^FLORINIA$", "FLORINEA")
        .adicionar("^FORTALEZA DO TABOCAO$", "TABOCAO")
        .adicionar("^SAO VALERIO DA NATIVIDADE$", "SAO VALERIO");

    padronizador.preparar();
    padronizador
}

pub fn criar_municipio_map() -> FxHashMap<String, String> {
    // a include_str! embute a string no código em tempo de compilação.
    let municipios_csv: &str = include_str!("data/municipios.csv");
    let mut mapa = FxHashMap::<String, String>::default();

    for linha in municipios_csv.lines().skip(1) {
        let cols: Vec<&str> = linha.split(",").collect();
        let codigo = cols.first().unwrap();
        let nome = normalizar(cols.get(1).unwrap()).into_owned();

        // Adiciona código do ibge no mapa
        mapa.insert(codigo.to_string(), nome.clone());
        mapa.insert(codigo[..codigo.len() - 1].to_string(), nome.clone());
    }
    mapa
}

// ====== Funções Públicas =======

/// Padroniza uma string representando município brasileiros.
///
/// ```
/// use enderecobr_rs::padronizar_municipios;
/// assert_eq!(padronizar_municipios("3304557"), "RIO DE JANEIRO");
/// assert_eq!(padronizar_municipios("003304557"), "RIO DE JANEIRO");
/// assert_eq!(padronizar_municipios("  3304557  "), "RIO DE JANEIRO");
/// assert_eq!(padronizar_municipios("RIO DE JANEIRO"), "RIO DE JANEIRO");
/// assert_eq!(padronizar_municipios("rio de janeiro"), "RIO DE JANEIRO");
/// assert_eq!(padronizar_municipios("SÃO PAULO"), "SAO PAULO");
/// assert_eq!(padronizar_municipios("PARATI"), "PARATY");
/// assert_eq!(padronizar_municipios("AUGUSTO SEVERO"), "CAMPO GRANDE");
/// assert_eq!(padronizar_municipios("SAO VALERIO DA NATIVIDADE"), "SAO VALERIO");
/// assert_eq!(padronizar_municipios(""), "");
/// ```
///
/// # Detalhes
/// Operações realizadas durante a padronização:
/// - remoção de espaços em branco antes e depois das strings e remoção de espaços em excesso entre palavras;
/// - conversão de caracteres para caixa alta;
/// - remoção de zeros à esquerda;
/// - busca, a partir do código numérico, do nome completo de cada município;
/// - remoção de acentos e caracteres não ASCII, correção de erros ortográficos frequentes e atualização
///   de nomes conforme listagem de municípios do IBGE de 2022.
///
/// Note que existe uma etapa de compilação das expressões regulares utilizadas,
/// logo a primeira execução desta função pode demorar um pouco a mais.
///
pub fn padronizar_municipios(valor: &str) -> String {
    let padronizador = &*PADRONIZADOR;
    let res = padronizador.padronizar(valor);

    let municipios = &*MUNICIPIOS_MAP;
    municipios.get(&res).unwrap_or(&res).to_string()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn padroniza_corretamente() {
        assert_eq!(padronizar_municipios("3304557"), "RIO DE JANEIRO");
        assert_eq!(padronizar_municipios("330455"), "RIO DE JANEIRO");
        assert_eq!(padronizar_municipios("03304557"), "RIO DE JANEIRO");
        assert_eq!(padronizar_municipios("0330455"), "RIO DE JANEIRO");
        assert_eq!(padronizar_municipios(" 3304557 "), "RIO DE JANEIRO");
        assert_eq!(padronizar_municipios("rio de janeiro"), "RIO DE JANEIRO");
        assert_eq!(padronizar_municipios(""), ""); // string vazia → string vazia
        assert_eq!(padronizar_municipios("SÃO PAULO"), "SAO PAULO");
        assert_eq!(padronizar_municipios("MOJI MIRIM"), "MOGI MIRIM");
        assert_eq!(padronizar_municipios("PARATI"), "PARATY");
    }
}
