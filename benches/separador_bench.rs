use std::hint::black_box;

use criterion::{criterion_group, criterion_main, Criterion};
use enderecobr_rs::separador_endereco::{segmentar_endereco, OpcoesSegmentacao};

pub fn separador_bench(c: &mut Criterion) {
    // Só para garantir que o modelo foi baixado antes de medir.
    let _aquecimento = segmentar_endereco("R Azul, 123", &OpcoesSegmentacao::sem_probabilidades());
    let _aquecimento = segmentar_endereco("R Azul, 123", &OpcoesSegmentacao::com_probabilidades());

    // Endereços de tamanhos/estruturas diferentes: logradouro longo com
    // complemento, endereço curto e endereço com número, siglas e CEP.
    let enderecos: [&str; 3] = [
        "RUA EDUARDO VIEIRA DE ALMEIDA, 520, RESIDENCIAL BOM JARDIM",
        "av n sra copacabana, 123, apt 301",
        "SQS 108 BL B AP 101, BRASILIA, DF, 70330-000",
    ];

    for (nome, opcoes) in [
        (
            "separador_endereco",
            &OpcoesSegmentacao::sem_probabilidades(),
        ),
        (
            "separador_endereco_probabilidades",
            &OpcoesSegmentacao::com_probabilidades(),
        ),
    ] {
        let mut group = c.benchmark_group(nome);
        for e in enderecos {
            group.bench_with_input(e, &e, |b, &n| {
                b.iter(|| segmentar_endereco(black_box(n), opcoes));
            });
        }
    }
}

criterion_group!(benches, separador_bench);
criterion_main!(benches);
