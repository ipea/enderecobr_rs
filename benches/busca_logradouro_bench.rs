#![cfg(feature = "busca_fuzzy")]

use std::{fs::File, hint::black_box};

use arrow::array::{Array, StringArray};
use criterion::{criterion_group, criterion_main, Criterion};
use enderecobr_rs::busca_fuzzy::busca_logradouro::{
    ErroSerdeIndice, GeocodeBrIndexer, SearchParams,
};
use parquet::arrow::arrow_reader::ParquetRecordBatchReaderBuilder;

fn create_ngram_index() -> Result<GeocodeBrIndexer, ErroSerdeIndice> {
    let file_name = "datasets/dados/indice.msgpack";

    let mut index = GeocodeBrIndexer::carregar(file_name)?;
    index.preparar_pools();
    Ok(index)
}

fn ler_dataset() -> Vec<(String, String, String, String, String)> {
    let file = File::open("datasets/dados/brutos/large_sample.parquet").unwrap();
    let builder = ParquetRecordBatchReaderBuilder::try_new(file).unwrap();

    let reader = builder.build().unwrap();

    let mut res: Vec<(String, String, String, String, String)> = Vec::new();

    for batch_res in reader {
        let batch = batch_res.unwrap();

        let ufs = batch
            .column_by_name("uf")
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
            .column_by_name("bairro")
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

            res.push((
                uf.to_string(),
                mun.to_string(),
                logr.to_string(),
                loc.to_string(),
                cep.to_string(),
            ));
        }
    }

    res
}

fn simular_geocodebr(trig: &GeocodeBrIndexer, dados: (&str, &str, &str, &str, &str)) {
    let mut res = trig.busca(
        dados.0,
        dados.1,
        dados.2,
        Some(dados.3),
        Some(dados.4),
        &SearchParams::default(),
    );

    if res.is_none() {
        res = trig.busca(
            dados.0,
            dados.1,
            dados.2,
            Some(dados.3),
            None,
            &SearchParams::default(),
        );
    }

    if res.is_none() {
        res = trig.busca(
            dados.0,
            dados.1,
            dados.2,
            None,
            Some(dados.4),
            &SearchParams::default(),
        );
    }

    if res.is_none() {
        trig.busca(
            dados.0,
            dados.1,
            dados.2,
            None,
            None,
            &SearchParams::default(),
        );
    }
}

pub fn busca_logradouro_bench(c: &mut Criterion) {
    let dataset = ler_dataset();
    let index = create_ngram_index().unwrap();

    c.bench_function("busca_logradouro_dataset_completo", |b| {
        b.iter(|| {
            dataset.iter().for_each(|(a, b, c, d, e)| {
                simular_geocodebr(
                    black_box(&index),
                    black_box((a.as_str(), b.as_str(), c.as_str(), d.as_str(), e.as_str())),
                );
            });
        });
    });
}

criterion_group!(benches, busca_logradouro_bench);
criterion_main!(benches);
