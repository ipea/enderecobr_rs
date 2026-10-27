use std::{
    fs,
    path::{Path, PathBuf},
    process,
    time::Duration,
};
/// Endereço de onde o modelo padrão é baixado.
pub const MODEL_DOWNLOAD_PATH: &str =
    "https://github.com/ipea/enderecobr_rs/releases/download/modelo-crf-v0.1/tagger.crf";

/// Versão do modelo padrão. É usado como subdiretório no cache para que
/// versões diferentes não se sobrescrevam.
pub const VERSAO_MODELO: &str = "modelo-crf-v0.1";

/// Nome do diretório da biblioteca dentro do cache do sistema.
pub const NOME_DIRETORIO_CACHE: &str = "enderecobr_rs";

/// Nome do arquivo do modelo dentro do diretório de cache.
pub const NOME_ARQUIVO_MODELO: &str = "tagger.crf";

/// Diretório (arquivo ou diretório) onde o modelo deve ficar.
pub const VAR_AMBIENTE_MODELO: &str = "ENDERECOBR_MODELO";

/// Desabilita o download do modelo.
pub const VAR_AMBIENTE_SEM_DOWNLOAD: &str = "ENDERECOBR_MODELO_SEM_DOWNLOAD";

/// Retorna o caminho configurado do modelo, baixando-o caso ainda não
/// exista localmente. É usado internamente por
/// [`segmentar_endereco`](super::segmentar_endereco).
///
/// A função retorna o caminho usando esta lista de prioridades:
///
/// 1. `path_modelo`, quando informado e não vazio;
/// 2. a variável de ambiente `ENDERECOBR_MODELO`, quando definida e não
///    vazia;
/// 3. o diretório de cache do sistema operacional (`~/.cache/...` no Linux,
///    `~/Library/Caches` no macOS, `%LOCALAPPDATA%` no Windows), no caminho
///    `enderecobr_rs/<versão do modelo>/tagger.crf`.
///
/// Se um diretório foi informado no argumento ou na variável de ambiente,
/// a função irá criar um novo diretório para cada uma das versões do modelo.
/// Caso seja um arquivo, ele será usado diretamente.
///
/// O arquivo só é baixado quando está ausente ou vazio. Use a variável de ambiente
/// `ENDERECOBR_MODELO_SEM_DOWNLOAD=1` para evitar o download em CIs.
///
/// A função retorna `Err` quando não consegue criar o diretório de destino,
/// fazer o download, ou gravar o modelo no local.
///
#[cfg_attr(coverage_nightly, coverage(off))] // Chama funções que acessam o disco.
pub fn obter_modelo(path_modelo: Option<&Path>) -> Result<PathBuf, String> {
    let caminho = obter_caminho_modelo(path_modelo)?;
    let sem_download = variavel_ambiente_ativa(VAR_AMBIENTE_SEM_DOWNLOAD);

    // Não faz a checagem de path também senão for pra fazer o download.
    if sem_download
        || caminho
            .metadata()
            .is_ok_and(|metadados| metadados.is_file() && metadados.len() > 0)
    {
        return Ok(caminho);
    }

    if !variavel_ambiente_ativa(VAR_AMBIENTE_SEM_DOWNLOAD) {
        baixar_modelo(&caminho)?;
    }
    Ok(caminho)
}

/// Resolve onde o modelo deve ficar, aplicando a ordem de prioridade
/// parâmetro > variável de ambiente > cache. Adiciona um subdiretório de versão
/// se o resultado for um diretório.
/// Usado em [`obter_modelo`].
pub fn obter_caminho_modelo(path_modelo: Option<&Path>) -> Result<PathBuf, String> {
    let path_param = path_modelo
        .filter(|x| !x.as_os_str().is_empty())
        .map(Path::to_path_buf);
    let path_env = std::env::var_os(VAR_AMBIENTE_MODELO)
        .filter(|x| !x.is_empty())
        .map(PathBuf::from);

    // O caminho padrão é um diretório por construção, então a versão e o
    // nome do arquivo são sempre anexados — o `is_dir` abaixo não serve
    // para este caso: num primeiro uso o diretório ainda não existe e o
    // modelo acabaria gravado no lugar do próprio diretório.
    let path_default = dirs::cache_dir().map(|x| {
        x.join(NOME_DIRETORIO_CACHE)
            .join(VERSAO_MODELO)
            .join(NOME_ARQUIVO_MODELO)
    });

    path_param
        .or(path_env)
        .or(path_default)
        .map(|cam| {
            if cam.is_dir() || cam.to_string_lossy().ends_with(['/', '\\']) {
                cam.join(VERSAO_MODELO).join(NOME_ARQUIVO_MODELO)
            } else {
                cam
            }
        })
        // Pra chegar aqui, só se realmente ele não conseguiu chegar no cache.
        .ok_or("Diretório de cache do sistema operacional indisponível".to_string())
}

// Acessa disco e rede; fica fora do alvo de cobertura.
#[cfg_attr(coverage_nightly, coverage(off))]
fn baixar_modelo(destino: &Path) -> Result<(), String> {
    if let Some(diretorio) = destino.parent().filter(|dir| !dir.as_os_str().is_empty()) {
        fs::create_dir_all(diretorio)
            .map_err(|erro| format!("Não foi possível criar {}: {erro}", diretorio.display()))?;
    }

    let bytes = obter_bytes_modelo()?;

    let temporario = destino.with_extension(format!("{}.tmp", process::id()));
    fs::write(&temporario, &bytes).map_err(|erro| {
        format!(
            "Não foi possível gravar o modelo {}: {erro}",
            temporario.display()
        )
    })?;

    let res = fs::rename(&temporario, destino).map_err(|erro| {
        format!(
            "Não foi possível renomear o arquivo do modelo {}: {erro}",
            temporario.display()
        )
    });

    if res.is_err() {
        fs::remove_file(&temporario).map_err(|erro| {
            format!(
                "Não foi remover o arquito temporário {}: {erro}",
                temporario.display()
            )
        })?;
    }
    Ok(())
}

// Baixa o conteúdo do modelo, validando o status HTTP antes de aceitar o corpo.
#[cfg_attr(coverage_nightly, coverage(off))]
fn obter_bytes_modelo() -> Result<Vec<u8>, String> {
    let cliente = reqwest::blocking::Client::builder()
        .timeout(Duration::from_secs(60))
        .user_agent(concat!(
            env!("CARGO_PKG_NAME"),
            "/",
            env!("CARGO_PKG_VERSION")
        ))
        .build()
        .map_err(|erro| format!("Não foi possível criar o cliente HTTP: {erro}"))?;

    let resposta = cliente
        .get(MODEL_DOWNLOAD_PATH)
        .send()
        .map_err(|erro| format!("Falha ao baixar o modelo: {erro}"))?;

    // O `reqwest` só devolve `Err` para falhas de transporte: um 404 ou 500 chega
    // como `Ok` e, sem esta checagem, o HTML do erro viraria o arquivo do modelo.
    let status = resposta.status();
    if !status.is_success() {
        return Err(format!("O download do modelo falhou com HTTP {status}"));
    }

    resposta
        .bytes()
        .map(|bytes| bytes.to_vec())
        .map_err(|erro| format!("Falha ao ler o corpo do download do modelo: {erro}"))
}

/// Variável de ambiente definida com um valor considerado "ligado"
/// (presente, não vazia e diferente de `0`/`false`).
fn variavel_ambiente_ativa(nome: &str) -> bool {
    std::env::var_os(nome)
        .is_some_and(|valor| !valor.is_empty() && valor != "0" && valor != "false")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_obter_caminho_modelo_arquivo() {
        std::env::set_var(VAR_AMBIENTE_MODELO, "/tmp/modelo_env/");

        assert_eq!(
            obter_caminho_modelo(None),
            Ok(PathBuf::from("/tmp/modelo_env/")
                .join(VERSAO_MODELO)
                .join(NOME_ARQUIVO_MODELO))
        );

        assert_eq!(
            obter_caminho_modelo(Some(Path::new("/tmp/modelo_argumento/"))),
            Ok(PathBuf::from("/tmp/modelo_argumento/")
                .join(VERSAO_MODELO)
                .join(NOME_ARQUIVO_MODELO))
        );

        assert_eq!(
            obter_caminho_modelo(Some(Path::new("/tmp/modelo_arquivo.crf"))),
            Ok(PathBuf::from("/tmp/modelo_arquivo.crf"))
        );

        // Parâmetro vazio é ignorado e cai na variável de ambiente.
        assert_eq!(
            obter_caminho_modelo(Some(Path::new(""))),
            Ok(PathBuf::from("/tmp/modelo_env/")
                .join(VERSAO_MODELO)
                .join(NOME_ARQUIVO_MODELO))
        );

        // Variável de ambiente vazia também é ignorada e cai no cache.
        std::env::set_var(VAR_AMBIENTE_MODELO, "");
        let caminho_cache = dirs::cache_dir().map(|x| {
            x.join(NOME_DIRETORIO_CACHE)
                .join(VERSAO_MODELO)
                .join(NOME_ARQUIVO_MODELO)
        });
        assert_eq!(obter_caminho_modelo(None).ok(), caminho_cache.clone());

        // Sem variável de ambiente, segue o cache do sistema.
        std::env::remove_var(VAR_AMBIENTE_MODELO);
        assert_eq!(obter_caminho_modelo(None).ok(), caminho_cache);
    }

    #[test]
    fn test_obter_modelo_sem_download_nao_baixa() {
        // Com o download desativado, o caminho é devolvido mesmo sem existir.
        std::env::set_var(VAR_AMBIENTE_SEM_DOWNLOAD, "1");

        let caminho = Path::new("/tmp/modelo_que_nunca_existiu.crf");
        assert_eq!(obter_modelo(Some(caminho)), Ok(PathBuf::from(caminho)));
    }

    #[test]
    fn test_obter_modelo_arquivo_existente_nao_baixa() {
        // O `Cargo.toml` existe e não é vazio: é devolvido sem download,
        // mesmo com o download ativado.
        std::env::set_var(VAR_AMBIENTE_SEM_DOWNLOAD, "0");

        let caminho = Path::new("Cargo.toml");
        assert_eq!(obter_modelo(Some(caminho)), Ok(PathBuf::from(caminho)));

        std::env::remove_var(VAR_AMBIENTE_SEM_DOWNLOAD);
    }

    #[test]
    fn test_variavel_ambiente_ativa() {
        std::env::set_var(VAR_AMBIENTE_SEM_DOWNLOAD, "true");
        assert!(variavel_ambiente_ativa(VAR_AMBIENTE_SEM_DOWNLOAD));
        std::env::set_var(VAR_AMBIENTE_SEM_DOWNLOAD, "1");
        assert!(variavel_ambiente_ativa(VAR_AMBIENTE_SEM_DOWNLOAD));
        std::env::set_var(VAR_AMBIENTE_SEM_DOWNLOAD, "false");
        assert!(!variavel_ambiente_ativa(VAR_AMBIENTE_SEM_DOWNLOAD));
        std::env::set_var(VAR_AMBIENTE_SEM_DOWNLOAD, "0");
        assert!(!variavel_ambiente_ativa(VAR_AMBIENTE_SEM_DOWNLOAD));
        std::env::remove_var(VAR_AMBIENTE_SEM_DOWNLOAD);
    }
}
