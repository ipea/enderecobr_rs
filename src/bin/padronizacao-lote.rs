use std::path::PathBuf;
use std::process::ExitCode;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Arc;
use std::time::{Duration, Instant};

use clap::Parser;
use enderecobr_rs::padronizar_estados_para_sigla;
use enderecobr_rs::separador_endereco::estruturar_segmentos;
use enderecobr_rs::separador_endereco::modelo::VAR_AMBIENTE_MODELO;
use enderecobr_rs::{
    padronizar_bairros, padronizar_cep_leniente, padronizar_complementos, padronizar_logradouros,
    padronizar_municipios, padronizar_numeros, padronizar_tipo_logradouro,
    separador_endereco::segmentar_endereco, Endereco,
};
use itertools::Itertools;
use polars::prelude::{
    col, sync_on_close::SyncOnCloseType, Column, DataFrame, DataType, Field, FileWriteFormat,
    IntoColumn, LazyFrame, ParquetCompression, ParquetWriteOptions, PlRefPath, PolarsError,
    PolarsResult, ScanArgsParquet, Schema, SinkDestination, SinkTarget, StatisticsOptions,
    StringChunked, UnifiedSinkArgs,
};

#[derive(Debug, Clone)]
enum TipoCampo {
    Logradouro,
    TipoLogradouro,
    Numero,
    Complemento,
    Localidade,
    Municipio,
    Estado,
    Cep,
}

#[derive(Debug, Clone)]
struct EspecificacaoCampo {
    tipo: TipoCampo,
    origem: String,
    destino: String,
}

fn identificar_campo(tipo_campo: &str) -> Result<TipoCampo, String> {
    match tipo_campo.to_lowercase().as_str() {
        "logradouro" | "logr" => Ok(TipoCampo::Logradouro),
        "tipo_logradouro" | "tipo_logr" => Ok(TipoCampo::TipoLogradouro),
        "numero" | "num" => Ok(TipoCampo::Numero),
        "complemento" | "comp" => Ok(TipoCampo::Complemento),
        "bairro" | "localidade" | "loc" => Ok(TipoCampo::Localidade),
        "estado" | "uf" => Ok(TipoCampo::Estado),
        "municipio" | "mun" => Ok(TipoCampo::Municipio),
        "cep" => Ok(TipoCampo::Cep),
        _ => Err(format!("Tipo desconhecido: {}", tipo_campo)),
    }
}

fn parsear(s: &str) -> Result<EspecificacaoCampo, String> {
    let partes: Vec<_> = s.split(':').collect();
    let [tipo, origem, destino] = partes.as_slice() else {
        return Err("Formato esperado: tipo:src:dst".into());
    };

    Ok(EspecificacaoCampo {
        tipo: identificar_campo(tipo)?,
        origem: (*origem).to_string(),
        destino: (*destino).to_string(),
    })
}

fn parsear_threads(s: &str) -> Result<usize, String> {
    match s.parse::<usize>() {
        Ok(n) if n > 0 => Ok(n),
        Ok(_) => Err("O número de threads deve ser maior que zero".into()),
        Err(_) => Err(format!("Número de threads inválido: {s}")),
    }
}

fn obter_padronizador(tipo: &TipoCampo) -> fn(&str) -> String {
    match tipo {
        TipoCampo::Logradouro => padronizar_logradouros,
        TipoCampo::TipoLogradouro => padronizar_tipo_logradouro,
        TipoCampo::Numero => padronizar_numeros,
        TipoCampo::Complemento => padronizar_complementos,
        TipoCampo::Localidade => padronizar_bairros,
        TipoCampo::Municipio => padronizar_municipios,
        TipoCampo::Estado => |x| padronizar_estados_para_sigla(x).to_string(),
        TipoCampo::Cep => padronizar_cep_leniente,
    }
}

/// Utilitário que serve para processar um arquivo parquet com as funções do enderecobr_rs.
#[derive(Debug, Parser)]
#[clap(author, version)]
struct Args {
    /// Caminho do arquivo PARQUET de entrada.
    arquivo_entrada: String,

    /// Caminho do arquivo PARQUET de saída.
    #[arg(short('o'), long, default_value = "./resultado.parquet")]
    arquivo_saida: String,

    /// Se deve manter todos campos
    #[arg(short('M'), long, default_value = "false")]
    manter_todos: bool,

    /// Campos que devem ser mantidos
    #[arg(short('m'), long, num_args = 1..,)]
    manter: Vec<String>,

    /// Limite de linhas a serem processadas. Usado para execuções de teste.
    #[arg(short('n'), long)]
    limite: Option<u32>,

    /// Coluna com o endereço bruto, a ser separado e padronizado em campos
    /// (logradouro, número, complemento, localidade e CEP).
    #[arg(short('e'), long)]
    endereco: Option<String>,

    /// Mede e imprime o tempo gasto na segmentação dos endereços. Só tem efeito
    /// combinado com `-e/--endereco`.
    #[arg(long, default_value = "false")]
    timing: bool,

    /// Número máximo de threads (cores) usadas no processamento. Sem esta opção,
    /// o Polars usa todos os núcleos disponíveis.
    #[arg(
        short('j'),
        long,
        value_name = "N",
        value_parser = parsear_threads
    )]
    threads: Option<usize>,

    /// Leitura de baixa memória do parquet de entrada. Desative com
    /// `--low-memory=false`.
    #[arg(long, default_value_t = true, action = clap::ArgAction::Set)]
    low_memory: bool,

    /// Especificação dos campos a serem processados.
    #[arg(
        short('c'),
        long = "campos",
        value_name = "TIPO_CAMPO:CAMPO_ORIGEM:CAMPO_DESTINO",
        num_args = 1..,
        value_parser = parsear
    )]
    campos: Vec<EspecificacaoCampo>,

    /// Caminho do modelo CRF usado na segmentação de `-e/--endereco`.
    #[arg(long, value_name = "ARQUIVO")]
    modelo: Option<PathBuf>,
}

fn processar_campo(df: LazyFrame, campo: &EspecificacaoCampo, schema: &Arc<Schema>) -> LazyFrame {
    let padronizador = obter_padronizador(&campo.tipo);
    let field = Field::new(campo.destino.as_str().into(), DataType::String);

    // Verifica se o campo é float para forçar um typecast antes
    // para int e então fazer o cast final para string
    let mut _df = match schema.get(&campo.origem) {
        Some(DataType::Float32) | Some(DataType::Float64) => {
            df.with_column(col(&campo.origem).cast(DataType::Int32))
        }
        _ => df,
    };

    _df.with_column(
        col(&campo.origem)
            .cast(DataType::String)
            .map(
                move |coluna: Column| {
                    let iterador = coluna.str()?.iter().map(|opt| opt.map(padronizador));
                    let nova_coluna = StringChunked::from_iter(iterador).into_column();
                    Ok(nova_coluna)
                },
                move |_, _| Ok(field.clone()),
            )
            .alias(&campo.destino),
    )
}

/// Nomes das colunas (e dos campos do struct) extraídos pelo `-e/--endereco`.
const CAMPOS_ENDERECO: [&str; 5] = [
    "logradouro_extraido",
    "numero_extraido",
    "complemento_extraido",
    "localidade_extraido",
    "cep_extraido",
];

/// Acumuladores do modo `--timing` (nanossegundos gastos e nº de endereços).
static TEMPO_SEGMENTACAO_NS: AtomicU64 = AtomicU64::new(0);
static NUM_ENDERECOS: AtomicU64 = AtomicU64::new(0);

fn campo_endereco_processado() -> Field {
    let campos = CAMPOS_ENDERECO
        .iter()
        .map(|&nome| Field::new(nome.into(), DataType::String))
        .collect();
    Field::new("endereco_processado".into(), DataType::Struct(campos))
}

/// Segmenta o endereço e padroniza os campos; no modo `--timing`, acumula ainda o
/// tempo gasto na segmentação.
fn segmentar_padronizado(texto: &str, timing: bool) -> Endereco {
    let Some(inicio) = timing.then(Instant::now) else {
        return estruturar_segmentos(&segmentar_endereco(texto), true);
    };

    let segmentado = segmentar_endereco(texto);
    TEMPO_SEGMENTACAO_NS.fetch_add(inicio.elapsed().as_nanos() as u64, Ordering::Relaxed);
    NUM_ENDERECOS.fetch_add(1, Ordering::Relaxed);
    estruturar_segmentos(&segmentado, true)
}

fn expandir_endereco(col: Column, timing: bool) -> PolarsResult<Column> {
    let enderecos: Vec<Option<Endereco>> = col
        .str()?
        .iter()
        .map(|opt| opt.map(|texto| segmentar_padronizado(texto, timing)))
        .collect();

    let extratores: [fn(&Endereco) -> Option<String>; 5] = [
        |e| e.logradouro.clone(),
        |e| e.numero.clone(),
        |e| e.complemento.clone(),
        |e| e.localidade.clone(),
        |e| e.cep.clone(),
    ];
    let colunas: Vec<Column> = CAMPOS_ENDERECO
        .iter()
        .zip(extratores)
        .map(|(&nome, extrair)| {
            let valores: Vec<Option<String>> = enderecos
                .iter()
                .map(|endereco| endereco.as_ref().and_then(extrair))
                .collect();
            Column::new(nome.into(), valores)
        })
        .collect();

    let df = DataFrame::new_infer_height(colunas)?;
    Ok(df.into_struct("endereco_processado".into()).into_column())
}

fn segmentar_endereco_df(
    df: LazyFrame,
    campo_endereco: &str,
    timing: bool,
) -> PolarsResult<LazyFrame> {
    // df.select([col(campo_endereco)])
    Ok(df
        .with_column(
            col(campo_endereco)
                .map(
                    move |coluna: Column| expandir_endereco(coluna, timing),
                    |_, _| Ok(campo_endereco_processado()),
                )
                .alias("endereco_processado"),
        )
        .with_columns(
            CAMPOS_ENDERECO
                .iter()
                .map(|&nome| col("endereco_processado").struct_().field_by_name(nome))
                .collect::<Vec<_>>(),
        )
        .drop(
            col("endereco_processado")
                .into_selector()
                .ok_or_else(|| PolarsError::ColumnNotFound("endereco_processado".into()))?,
        ))
}

fn imprimir_timing(duracao_total: Duration) {
    println!("Tempo total de execução: {:.2?}", duracao_total);

    let n = NUM_ENDERECOS.load(Ordering::Relaxed);
    if n == 0 {
        return;
    }

    let tempo_segmentacao = Duration::from_nanos(TEMPO_SEGMENTACAO_NS.load(Ordering::Relaxed));
    let media_us = tempo_segmentacao.as_secs_f64() * 1e6 / n as f64;
    println!(
        "Separação de endereços: {tempo_segmentacao:.2?} no total, {media_us:.2} µs por endereço (n={n})"
    );
}

/// Limita o número de threads usadas pelo Polars e pelo Rayon.
///
/// As variáveis de ambiente precisam ser definidas antes de qualquer uso do
/// Polars, que lê ambas ao criar o pool de threads na primeira chamada.
fn limitar_threads(threads: Option<usize>) {
    let Some(threads) = threads else {
        return;
    };

    std::env::set_var("POLARS_MAX_THREADS", threads.to_string());
    std::env::set_var("RAYON_NUM_THREADS", threads.to_string());
}

fn main() -> ExitCode {
    match executar(Args::parse()) {
        Ok(()) => ExitCode::SUCCESS,
        Err(erro) => {
            eprintln!("{erro}");
            ExitCode::FAILURE
        }
    }
}

/// Processa o arquivo; a falha vira mensagem no stderr e exit code 1.
fn executar(args: Args) -> Result<(), String> {
    limitar_threads(args.threads);

    // O modelo é escolhido pela mesma variável que a biblioteca já consulta.
    if let Some(modelo) = &args.modelo {
        std::env::set_var(VAR_AMBIENTE_MODELO, modelo);
    }

    let inicio_execucao = Instant::now();
    let timing = args.timing;
    let mut colunas_finais: Vec<String> = Vec::default();

    let mut df = LazyFrame::scan_parquet(
        PlRefPath::new(args.arquivo_entrada.as_str()),
        ScanArgsParquet {
            low_memory: args.low_memory,
            parallel: polars::prelude::ParallelStrategy::RowGroups,
            use_statistics: true,
            rechunk: true,
            ..Default::default()
        },
    )
    .map_err(|erro| format!("não foi possível ler {}: {erro}", args.arquivo_entrada))?
    .with_streaming(true);

    if let Some(limite) = args.limite {
        df = df.limit(limite);
    }

    let schema = df
        .collect_schema()
        .map_err(|erro| format!("não foi possível ler o schema: {erro}"))?;

    for campo in &args.campos {
        df = processar_campo(df, campo, &schema);
    }
    colunas_finais.extend(args.campos.iter().map(|c| c.destino.to_string()));

    if let Some(campo_endereco) = args.endereco {
        df = segmentar_endereco_df(df, &campo_endereco, timing)
            .map_err(|erro| format!("não foi possível segmentar os endereços: {erro}"))?;

        CAMPOS_ENDERECO
            .iter()
            .for_each(|x| colunas_finais.push(x.to_string()));
    }

    if !args.manter_todos {
        args.manter
            .iter()
            .for_each(|x| colunas_finais.push(x.to_owned()));

        let cols: Vec<_> = colunas_finais.iter().unique().map(col).collect();

        // Evita `select([])`, que zeraria o dataframe quando nenhum campo foi
        // computado nem solicitado para manter (ex.: apenas `-e`).
        if !colunas_finais.is_empty() {
            df = df.select(cols);
        }
    }

    let resultado = df
        .sink(
            SinkDestination::File {
                target: SinkTarget::Path(PlRefPath::new(args.arquivo_saida.as_str())),
            },
            FileWriteFormat::Parquet(Arc::new(ParquetWriteOptions {
                compression: ParquetCompression::Zstd(None),
                statistics: StatisticsOptions {
                    min_value: true,
                    max_value: true,
                    distinct_count: true,
                    null_count: true,
                    ..Default::default()
                },
                row_group_size: Some(10_000),
                data_page_size: Some(1024 * 1024),
                ..Default::default()
            })),
            UnifiedSinkArgs {
                sync_on_close: SyncOnCloseType::All,
                maintain_order: false,
                ..Default::default()
            },
        )
        .map_err(|erro| format!("não foi possível escrever {}: {erro}", args.arquivo_saida))?
        .collect_with_engine(polars::prelude::Engine::Streaming);

    resultado
        .map_err(|erro| format!("não foi possível escrever {}: {erro}", args.arquivo_saida))?;

    println!(
        "Arquivo \"{}\" foi processado com sucesso e salvo em \"{}\".",
        args.arquivo_entrada, args.arquivo_saida
    );
    if timing {
        imprimir_timing(inicio_execucao.elapsed());
    }

    Ok(())
}
