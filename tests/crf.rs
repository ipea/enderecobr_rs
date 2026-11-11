//! Testes de integração do segmentador.
//!
//! Precisam do modelo treinado, então ficam fora do crate e usam só a API
//! pública. Nada aqui baixa o modelo: quando ele não está no cache, como no CI
//! comum, os testes pulam. Com `TESTE_CRF_EXIGE_MODELO=1` a ausência do modelo
//! vira falha — é assim que o `bump-versao-modelo.sh` reprova um modelo ruim.

use std::path::PathBuf;
use std::sync::OnceLock;

use enderecobr_rs::separador_endereco::modelo::{VAR_AMBIENTE_MODELO, VAR_AMBIENTE_SEM_DOWNLOAD};
use enderecobr_rs::separador_endereco::{
    obter_caminho_modelo, EnderecoSegmentado, OpcoesEndereco, OpcoesSegmentacao, SegmentoEndereco,
    SeparadorEndereco, TipoSegmento,
};
use enderecobr_rs::{estruturar_endereco, segmentar_endereco, segmentar_enderecos, Endereco};

/// Quando definida, a ausência do modelo vira falha em vez de teste pulado. É o
/// que o `bump-versao-modelo.sh` usa para não publicar um modelo quebrado.
const VAR_AMBIENTE_EXIGE_MODELO: &str = "TESTE_CRF_EXIGE_MODELO";

/// Caminho do modelo padrão, quando ele já está no cache.
fn caminho_do_modelo() -> Option<PathBuf> {
    let caminho = obter_caminho_modelo(None).ok()?;
    let encontrado = caminho.is_file();
    assert!(
        encontrado || std::env::var_os(VAR_AMBIENTE_EXIGE_MODELO).is_none(),
        "modelo não encontrado em {}",
        caminho.display()
    );
    encontrado.then_some(caminho)
}

/// Aponta as variáveis de ambiente para o modelo do cache, uma única vez: assim
/// nenhum teste baixa o modelo e não há corrida no `set_var`.
fn preparar_modelo_padrao() -> bool {
    static PREPARO: OnceLock<bool> = OnceLock::new();
    *PREPARO.get_or_init(|| {
        let Some(caminho) = caminho_do_modelo() else {
            return false;
        };
        std::env::set_var(VAR_AMBIENTE_MODELO, &caminho);
        std::env::set_var(VAR_AMBIENTE_SEM_DOWNLOAD, "true");
        true
    })
}

/// Constrói um segmento sem repetir a struct em cada teste.
fn criar_segmento(valor: &str, tipo: TipoSegmento) -> SegmentoEndereco {
    SegmentoEndereco::novo(valor, tipo)
}

/// Constrói uma segmentação a partir dos segmentos, na ordem em que aparecem.
fn criar_segmentado(segmentos: Vec<SegmentoEndereco>) -> EnderecoSegmentado {
    EnderecoSegmentado::novo(segmentos)
}

/// Estrutura o endereço com o modelo padrão, já padronizado.
fn estruturar(texto: &str) -> Result<Endereco, String> {
    estruturar_endereco(texto, &OpcoesEndereco::default())
}

#[test]
fn segmentar_endereco_separa_partes_simples() {
    if !preparar_modelo_padrao() {
        return;
    }

    assert_eq!(
        segmentar_endereco("rua brasil, 123", &OpcoesSegmentacao::sem_probabilidades()),
        Ok(criar_segmentado(vec![
            criar_segmento("rua brasil", TipoSegmento::Logradouro),
            criar_segmento("123", TipoSegmento::Numero),
        ]))
    );
}

#[test]
fn segmentar_enderecos_mantem_a_ordem_da_entrada() {
    if !preparar_modelo_padrao() {
        return;
    }

    let entradas = ["rua brasil, 123", "av atlantica, 123, apto 301"];
    assert_eq!(
        segmentar_enderecos(&entradas, &OpcoesSegmentacao::sem_probabilidades()),
        Ok(vec![
            criar_segmentado(vec![
                criar_segmento("rua brasil", TipoSegmento::Logradouro),
                criar_segmento("123", TipoSegmento::Numero),
            ]),
            criar_segmentado(vec![
                criar_segmento("av atlantica", TipoSegmento::Logradouro),
                criar_segmento("123", TipoSegmento::Numero),
                criar_segmento("apto 301", TipoSegmento::Complemento),
            ]),
        ])
    );
}

#[test]
fn carregar_permite_segmentar_com_o_modelo_do_cache() {
    let Some(caminho) = caminho_do_modelo() else {
        return;
    };
    let separador = SeparadorEndereco::carregar(caminho).unwrap();

    let features = separador
        .extrator
        .tokens2features(&["rua", "brasil", "123"]);
    assert_eq!(features.len(), 3);
    for features_token in &features {
        assert!(!features_token.is_empty());
    }

    assert_eq!(
        separador.segmentar("rua brasil, 123", &OpcoesSegmentacao::sem_probabilidades()),
        criar_segmentado(vec![
            criar_segmento("rua brasil", TipoSegmento::Logradouro),
            criar_segmento("123", TipoSegmento::Numero),
        ])
    );
}

#[test]
fn probabilidades_preenchem_trechos_e_endereco() {
    let Some(caminho) = caminho_do_modelo() else {
        return;
    };
    let separador = SeparadorEndereco::carregar(caminho).unwrap();

    let segmentado =
        separador.segmentar("rua brasil, 123", &OpcoesSegmentacao::com_probabilidades());

    let trechos: Vec<(&str, TipoSegmento)> = segmentado
        .segmentos
        .iter()
        .map(|segmento| (segmento.valor.as_str(), segmento.tipo))
        .collect();
    assert_eq!(
        trechos,
        vec![
            ("rua brasil", TipoSegmento::Logradouro),
            ("123", TipoSegmento::Numero),
        ]
    );

    // A probabilidade do endereço nunca é maior que a de um de seus trechos.
    let total = segmentado.probabilidade.expect("probabilidade do endereço");
    assert!(total > 0.0 && total <= 1.0);
    for segmento in &segmentado.segmentos {
        let probabilidade = segmento.probabilidade.expect("probabilidade do trecho");
        assert!(probabilidade > 0.0 && probabilidade <= 1.0);
        assert!(probabilidade >= total);
    }

    // A confiança é a média geométrica das marginais: normalizada pelo
    // tamanho, então não despenca como a probabilidade do endereço todo.
    let confianca = segmentado.confianca.expect("confiança do endereço");
    assert!(confianca > 0.0 && confianca <= 1.0);
    // Duas métricas distintas: a do caminho inteiro é menor que a média por token.
    assert!(confianca > total, "confianca {confianca} <= total {total}");
}

#[test]
fn sem_a_opcao_as_probabilidades_ficam_vazias() {
    if !preparar_modelo_padrao() {
        return;
    }

    let segmentado =
        segmentar_endereco("rua brasil, 123", &OpcoesSegmentacao::sem_probabilidades()).unwrap();
    assert_eq!(segmentado.probabilidade, None);
    assert_eq!(segmentado.confianca, None);
    assert_eq!(segmentado.segmentos[0].probabilidade, None);
}

#[test]
fn estruturar_endereco_leva_as_probabilidades_para_o_endereco() {
    if !preparar_modelo_padrao() {
        return;
    }

    let endereco = estruturar_endereco(
        "rua brasil, 123",
        &OpcoesEndereco::default().com_probabilidades(),
    )
    .unwrap();
    assert!(endereco.probabilidade.is_some_and(|p| p > 0.0 && p <= 1.0));
    assert!(endereco.confianca.is_some_and(|c| c > 0.0 && c <= 1.0));

    // O caminho comum não paga a passada extra.
    assert_eq!(estruturar("rua brasil, 123").unwrap().probabilidade, None);
}

#[test]
fn estruturar_endereco_padroniza_os_campos() {
    if !preparar_modelo_padrao() {
        return;
    }

    assert_eq!(
        estruturar("av atlantica, 123, apto 301").unwrap(),
        Endereco {
            logradouro: Some("AVENIDA ATLANTICA".to_string()),
            numero: Some("123".to_string()),
            complemento: Some("APARTAMENTO 301".to_string()),
            ..Default::default()
        }
    );
}

#[test]
fn estruturar_endereco_sem_padronizar_mantem_os_segmentos() {
    if !preparar_modelo_padrao() {
        return;
    }

    assert_eq!(
        estruturar_endereco(
            "av atlantica, 123, apto 301",
            &OpcoesEndereco::default().sem_padronizar()
        ),
        Ok(Endereco {
            logradouro: Some("av atlantica".to_string()),
            numero: Some("123".to_string()),
            complemento: Some("apto 301".to_string()),
            ..Default::default()
        })
    );
}

#[test]
fn estruturar_endereco_preenche_localidade_e_cep() {
    if !preparar_modelo_padrao() {
        return;
    }

    assert_eq!(
        estruturar("rua brasil, 123, ap 2, copacabana, rio de janeiro, rj, 22000-000").unwrap(),
        Endereco {
            logradouro: Some("RUA BRASIL".to_string()),
            numero: Some("123".to_string()),
            complemento: Some("APARTAMENTO 2".to_string()),
            localidade: Some("COPACABANA".to_string()),
            cep: Some("22000-000".to_string()),
            ..Default::default()
        }
    );
}

/// Casos de sanidade: invariantes que o modelo novo não pode quebrar. São os
/// mesmos que o `bump-versao-modelo.sh` roda antes de publicar uma versão.
#[test]
fn estruturacao_de_casos_de_sanidade() {
    if !preparar_modelo_padrao() {
        return;
    }

    let ceps = [
        "rua das flores 123, centro, sao paulo, sp, 01000-000",
        "rua das flores 123, centro, sao paulo, sp, 13000-000",
        "rua sete de setembro 33, centro, porto alegre, rs, 90010-190",
        "travessa sao jose 15 loja 3, centro, niteroi, rj, 24020-000",
    ];
    for texto in ceps {
        let esperado = texto.rsplit(' ').next().unwrap();
        let obtido = estruturar(texto).unwrap();
        assert_eq!(obtido.cep.as_deref(), Some(esperado), "{texto}");
    }

    assert_eq!(
        estruturar("r a, n. 1, ap 2").unwrap().numero.as_deref(),
        Some("1")
    );
    assert_eq!(
        estruturar("av atlantica, 123, apto 301")
            .unwrap()
            .complemento
            .as_deref(),
        Some("APARTAMENTO 301")
    );
    assert_eq!(
        estruturar("rua brasil, 123").unwrap().logradouro.as_deref(),
        Some("RUA BRASIL")
    );
    assert_eq!(
        estruturar("av paulista 1578, bela vista, sao paulo, sp")
            .unwrap()
            .localidade
            .as_deref(),
        Some("BELA VISTA")
    );
}

/// Contrato de rotulagem: textos que já divergiram entre o Rust e o
/// python-crfsuite. Serve de teste de paridade quando o CRF troca de
/// biblioteca ou o modelo muda de versão.
#[test]
fn rotulagem_de_casos_conhecidos_nao_muda() {
    let Some(caminho) = caminho_do_modelo() else {
        return;
    };
    let separador = SeparadorEndereco::carregar(caminho).unwrap();

    let casos: [(&str, &[(&str, TipoSegmento)]); 4] = [
        (
            "AV FARQUAR, 1913 ARIGOLANDIA. 76801-209 Porto Velho - RO.",
            &[
                ("AV FARQUAR", TipoSegmento::Logradouro),
                ("1913", TipoSegmento::Numero),
                ("ARIGOLANDIA", TipoSegmento::Localidade),
                ("76801-209", TipoSegmento::Cep),
                ("Porto Velho", TipoSegmento::Municipio),
                ("RO", TipoSegmento::Uf),
            ],
        ),
        (
            "rodovia br 116 km 12, sitio sao jose, cep 01000-000",
            &[
                ("rodovia br 116", TipoSegmento::Logradouro),
                ("km 12", TipoSegmento::QuilometragemVia),
                ("sitio sao jose", TipoSegmento::NucleoRural),
            ],
        ),
        (
            "RUA DAS FLORES, 123 - APTO 45, CENTRO, 20000-000",
            &[
                ("RUA DAS FLORES", TipoSegmento::Logradouro),
                ("123", TipoSegmento::Numero),
                ("APTO 45", TipoSegmento::Complemento),
                ("CENTRO", TipoSegmento::Localidade),
                ("20000-000", TipoSegmento::Cep),
            ],
        ),
        (
            "q 3 lote 7 s/n, setor sul",
            &[
                ("q 3 lote 7", TipoSegmento::Parcela),
                ("s/n", TipoSegmento::Numero),
                ("setor sul", TipoSegmento::Localidade),
            ],
        ),
    ];

    for (texto, esperado) in casos {
        let segmentado = separador.segmentar(texto, &OpcoesSegmentacao::sem_probabilidades());
        let obtidos: Vec<(&str, TipoSegmento)> = segmentado
            .segmentos
            .iter()
            .map(|segmento| (segmento.valor.as_str(), segmento.tipo))
            .collect();
        assert_eq!(obtidos, esperado, "{texto}");
    }
}
