use std::hint::black_box;

use criterion::{criterion_group, criterion_main, Criterion};
use enderecobr_rs::separador_endereco::segmentar_endereco;

pub fn separador_bench(c: &mut Criterion) {
    let _ = segmentar_endereco("R Azul, 123"); // Só para garantir que o modelo foi baixado

    let enderecos: [&str; 1] = ["RUA EDUARDO VIEIRA DE ALMEIDA, 520, RESIDENCIAL BOM JARDIM"];
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
