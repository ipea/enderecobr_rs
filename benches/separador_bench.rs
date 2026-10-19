use std::hint::black_box;

use criterion::{criterion_group, criterion_main, Criterion};
use enderecobr_rs::separador_endereco::segmentar_endereco;

pub fn separador_bench(c: &mut Criterion) {
    let _ = segmentar_endereco("R Azul, 123"); // Só para garantir que o modelo foi baixado

    let enderecos: [&str; 5] = [
        "Rua Engenheiro Camilo Collier 692 Primavera 57304240 ADFIMA ARAPIRACA AL",
        "RUA EDUARDO VIEIRA DE ALMEIDA, 520, RESIDENCIAL BOM JARDIM",
        "AVENIDA BORBOREMA 853 EM FRENTE A PRACA JARDIM AEROPORTO",
        "R JOSE PICERNI,151AP 51,JD PANORAMA",
        "ASSENTAMENTO BEM TE VI, ASSENTAMENTO. 64613-000 Geminiano - PI",
    ];
    c.bench_function("separador_endereco", |b| {
        b.iter(|| {
            enderecos.iter().for_each(|e| {
                segmentar_endereco(black_box(e));
            });
        });
    });
}

criterion_group!(benches, separador_bench);
criterion_main!(benches);
