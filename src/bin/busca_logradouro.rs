use std::{
    fs::File,
    io::{self, BufRead},
    time::Instant,
};

use arrow::array::{Array, StringArray};
use clap::Parser;
use enderecobr_rs::busca_fuzzy::busca_logradouro::{
    ErroSerdeIndice, GeocodeBrIndexer, SearchParams,
};
use parquet::arrow::arrow_reader::ParquetRecordBatchReaderBuilder;

/// Utilitário iterativo para realizar pequenos testes de linha de comando com
/// a busca fuzzy por logradouro.
#[derive(Parser)]
#[clap(author, version)]
struct Args {
    #[arg(short('m'), long)]
    municipio: String,

    #[arg(short('e'), long)]
    estado: String,

    #[arg(short('l'), long)]
    localidade: Option<String>,

    #[arg(short('c'), long)]
    cep: Option<String>,

    #[arg(short('s'), long)]
    min_sim: Option<f32>,

    #[arg(short('o'), long)]
    min_overlap: Option<f32>,

    logradouro: Option<String>,
}

fn create_ngram_index() -> Result<GeocodeBrIndexer, ErroSerdeIndice> {
    let file_name = "datasets/dados/indice.bin";

    if let Ok(mut indice) = GeocodeBrIndexer::carregar(file_name) {
        indice.preparar_pools();
        return Ok(indice);
    }

    println!("Indexando...");
    let file = File::open("datasets/dados/brutos/logr_cep_loc.parquet")?;
    let builder = ParquetRecordBatchReaderBuilder::try_new(file).unwrap();

    let reader = builder.build().unwrap();
    let mut index = GeocodeBrIndexer::new(3);

    for batch_res in reader {
        let batch = batch_res.unwrap();

        let ufs = batch
            .column_by_name("estado")
            .unwrap()
            .as_any()
            .downcast_ref::<StringArray>()
            .unwrap();

        let muns = batch
            .column_by_name("municipio")
            .unwrap()
            .as_any()
            .downcast_ref::<StringArray>()
            .unwrap();

        let ceps = batch
            .column_by_name("cep")
            .unwrap()
            .as_any()
            .downcast_ref::<StringArray>()
            .unwrap();

        let locs = batch
            .column_by_name("localidade")
            .unwrap()
            .as_any()
            .downcast_ref::<StringArray>()
            .unwrap();

        let logrs = batch
            .column_by_name("logradouro")
            .and_then(|col| col.as_any().downcast_ref::<StringArray>());

        for i in 0..batch.num_rows() {
            let uf = ufs.value(i);
            let mun = muns.value(i);
            let cep = ceps.value(i);
            let loc = locs.value(i);

            let logr = logrs
                .filter(|arr| !arr.is_null(i))
                .map(|arr| arr.value(i))
                .unwrap();

            index.add(uf, mun, logr, Some(loc), Some(cep));
        }
    }

    index.finalizar();

    index.salvar(file_name)?;

    Ok(index)
}

fn realizar_busca(trig: &GeocodeBrIndexer, args: &Args, logradouro: Option<String>) {
    let mut params = SearchParams::default();

    if let Some(v) = args.min_overlap {
        params.sobreposicao_min_tokens = Some(v);
    }

    if let Some(v) = args.min_sim {
        params.similaridade_min = Some(v);
    }

    let inicio = Instant::now(); // Marca o início do tempo
    let sims = trig.busca(
        &args.estado,
        &args.municipio,
        logradouro.as_deref().unwrap_or(""),
        args.localidade.as_deref(),
        args.cep.as_deref(),
        &params,
    );
    let duracao = inicio.elapsed().as_micros();

    println!("{duracao} us: {sims:?}");
}

fn main() {
    let args = Args::parse();
    let trig = create_ngram_index().unwrap();

    if let Some(ref v) = args.logradouro {
        realizar_busca(&trig, &args, Some(v.clone()));
    } else {
        println!("> Logradouro:");
        let stdin = io::stdin();
        for line in stdin.lock().lines().map_while(Result::ok) {
            realizar_busca(&trig, &args, Some(line));
        }
    }
}
