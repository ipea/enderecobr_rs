use std::hint::black_box;

use criterion::{criterion_group, criterion_main, Criterion};
use enderecobr_rs::separador_endereco::segmentar_endereco;

pub fn separador_bench(c: &mut Criterion) {
    let _ = segmentar_endereco("R Azul, 123"); // Só para garantir que o modelo foi baixado

    // Endereços de tamanhos/estruturas diferentes: logradouro longo com
    // complemento, endereço curto e endereço com número, siglas e CEP.
    let enderecos: [&str; 3] = [
        "RUA EDUARDO VIEIRA DE ALMEIDA, 520, RESIDENCIAL BOM JARDIM",
        "av n sra copacabana, 123, apt 301",
        "SQS 108 BL B AP 101, BRASILIA, DF, 70330-000",
    ];

    let mut group = c.benchmark_group("separador_endereco");
    for e in enderecos {
        group.bench_with_input(e, &e, |b, &n| {
            b.iter(|| segmentar_endereco(black_box(n)));
        });
    }
}

criterion_group!(benches, separador_bench);
criterion_main!(benches);
