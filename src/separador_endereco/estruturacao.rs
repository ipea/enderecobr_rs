use crate::{
    endereco::padronizar_in_place,
    separador_endereco::{EnderecoSegmentado, TipoSegmento},
    Endereco,
};

/// Agrupa os segmentos nos campos de um [`Endereco`].
///
/// Cada tipo tem uma lista de campos preferidos (vide `campos_preferidos`) e o
/// trecho fica no primeiro deles ainda livre — é isso que resolve tanto a disputa
/// pelo mesmo campo quanto o tipo sem campo próprio. Trecho com a lista toda
/// preenchida, ou sem lista, é descartado.
///
/// ```
/// use enderecobr_rs::separador_endereco::{
///     estruturar_segmentos, EnderecoSegmentado, SegmentoEndereco, TipoSegmento
/// };
/// use enderecobr_rs::endereco::Endereco;
///
/// let segmentado = EnderecoSegmentado {
///     segmentos: vec![
///         SegmentoEndereco {
///             valor: "av atlantica".to_string(),
///             tipo: TipoSegmento::Logradouro,
///         },
///         SegmentoEndereco {
///             valor: "123".to_string(),
///             tipo: TipoSegmento::Numero,
///         },
///         SegmentoEndereco {
///             valor: "apt 203".to_string(),
///             tipo: TipoSegmento::Complemento,
///         },
///     ],
/// };
///
/// let resultado_esperado = Endereco {
///     logradouro: Some("AVENIDA ATLANTICA".to_string()),
///     numero: Some("123".to_string()),
///     complemento: Some("APARTAMENTO 203".to_string()),
///     ..Default::default()
/// };
///
/// assert_eq!(estruturar_segmentos(&segmentado, true), resultado_esperado);
/// ```
pub fn estruturar_segmentos(segmentado: &EnderecoSegmentado, padronizar: bool) -> Endereco {
    let mut res = Endereco::default();
    let mut anterior = None;
    for seg in &segmentado.segmentos {
        let (campos, concatenar) = campos_preferidos(seg.tipo, anterior);
        for campo in campos {
            let destino = match campo {
                Campo::Logradouro => &mut res.logradouro,
                Campo::Numero => &mut res.numero,
                Campo::Complemento => &mut res.complemento,
                Campo::Localidade => &mut res.localidade,
                Campo::Cep => &mut res.cep,
            };

            match destino {
                // Caso não exista nenhum valor no campo esperado, crio um novo
                None => {
                    *destino = Some(seg.valor.clone());
                    break;
                }
                // O trecho entra em sequência no campo já preenchido
                Some(atual) if concatenar => {
                    atual.push(' ');
                    atual.push_str(&seg.valor);
                    break;
                }
                // Se já existe algo, eu descarto por padrão.
                Some(_) => (),
            }
        }
        anterior = Some(seg.tipo);
    }

    if padronizar {
        padronizar_in_place(&mut res);
    }

    res
}

/// Campo do [`Endereco`] que pode receber um trecho.
#[derive(Clone, Copy)]
enum Campo {
    Logradouro,
    Numero,
    Complemento,
    Localidade,
    Cep,
}

/// Campos que um trecho pode ocupar, na ordem de preferência, e se ele entra em
/// sequência no primeiro campo já preenchido em vez de ser descartado.
///
/// A lista vazia descarta o trecho. Só o tipo do trecho e o do anterior entram na
/// decisão.
fn campos_preferidos(
    tipo: TipoSegmento,
    anterior: Option<TipoSegmento>,
) -> (&'static [Campo], bool) {
    use TipoSegmento::*;

    match tipo {
        Logradouro => (&[Campo::Logradouro], false),
        Numero | QuilometragemVia => (&[Campo::Numero, Campo::Complemento], false),
        Cep => (&[Campo::Cep], false),
        Parcela if anterior == Some(Logradouro) => (&[Campo::Logradouro], true),
        Parcela => (&[Campo::Logradouro, Campo::Complemento], true),
        NucleoRural | RecursoNatural | Empreendimento | PontoReferencia => {
            (&[Campo::Logradouro, Campo::Localidade], false)
        }
        Complemento => (&[Campo::Complemento], true),
        Localidade => (&[Campo::Localidade], false),
        Denominacao | Referencia | Municipio | Uf | Cadastro | Ruido | Outro => (&[], false),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::endereco::Endereco;
    use crate::separador_endereco::SegmentoEndereco;

    /// Constrói um segmento sem repetir a struct em cada teste.
    fn criar_segmento(valor: &str, tipo: TipoSegmento) -> SegmentoEndereco {
        SegmentoEndereco {
            valor: valor.to_string(),
            tipo,
        }
    }

    /// Constrói uma segmentação a partir dos segmentos, na ordem em que aparecem.
    fn criar_segmentado(segmentos: Vec<SegmentoEndereco>) -> EnderecoSegmentado {
        EnderecoSegmentado { segmentos }
    }

    #[test]
    fn segmento_como_endereco_agrupa_campos_padroes() {
        let segmentado = criar_segmentado(vec![
            criar_segmento("av atlantica", TipoSegmento::Logradouro),
            criar_segmento("123", TipoSegmento::Numero),
            criar_segmento("apt 203", TipoSegmento::Complemento),
            criar_segmento("copacabana", TipoSegmento::Localidade),
            criar_segmento("22000-000", TipoSegmento::Cep),
        ]);

        assert_eq!(
            estruturar_segmentos(&segmentado, true),
            Endereco {
                logradouro: Some("AVENIDA ATLANTICA".to_string()),
                numero: Some("123".to_string()),
                complemento: Some("APARTAMENTO 203".to_string()),
                localidade: Some("COPACABANA".to_string()),
                cep: Some("22000-000".to_string()),
            }
        );
    }

    #[test]
    fn segmento_como_endereco_resolve_tipos_sem_campo_pelo_contexto() {
        let segmentado = criar_segmentado(vec![
            criar_segmento("r x", TipoSegmento::Logradouro),
            // Segundo logradouro é ignorado: o campo já foi preenchido.
            criar_segmento("r y", TipoSegmento::Logradouro),
            // Único a disputar a localidade e não vem depois de número.
            criar_segmento("edifton bar", TipoSegmento::Empreendimento),
            // Referência não é numeração nem lugar: é descartada.
            criar_segmento("esquina com r b", TipoSegmento::Referencia),
            criar_segmento("antiga r c", TipoSegmento::Denominacao),
            criar_segmento("rio de janeiro", TipoSegmento::Municipio),
            criar_segmento("rj", TipoSegmento::Uf),
            criar_segmento("vale qualquer coisa", TipoSegmento::Outro),
        ]);

        assert_eq!(
            estruturar_segmentos(&segmentado, false),
            Endereco {
                logradouro: Some("r x".to_string()),
                localidade: Some("edifton bar".to_string()),
                ..Default::default()
            }
        );
    }

    #[test]
    fn segmento_como_endereco_concatena_parcela_ao_logradouro() {
        // Parcela é concatenável: entra em sequência no logradouro já preenchido.
        assert_eq!(
            estruturar_segmentos(
                &criar_segmentado(vec![
                    criar_segmento("r x", TipoSegmento::Logradouro),
                    criar_segmento("qd 5 lote 7", TipoSegmento::Parcela),
                    criar_segmento("asa norte", TipoSegmento::Complemento),
                ]),
                false,
            ),
            Endereco {
                logradouro: Some("r x qd 5 lote 7".to_string()),
                complemento: Some("asa norte".to_string()),
                ..Default::default()
            }
        );
    }

    #[test]
    fn segmento_como_endereco_promove_parcela_a_logradouro() {
        // Sem logradouro na linha, a parcela abre o endereço.
        let segmentado = criar_segmentado(vec![criar_segmento("qd 5", TipoSegmento::Parcela)]);

        assert_eq!(
            estruturar_segmentos(&segmentado, false),
            Endereco {
                logradouro: Some("qd 5".to_string()),
                ..Default::default()
            }
        );

        // Entre dois logradouros, a parcela concatena no primeiro.
        let entre_logradouros = criar_segmentado(vec![
            criar_segmento("r x", TipoSegmento::Logradouro),
            criar_segmento("qd 5", TipoSegmento::Parcela),
            criar_segmento("r y", TipoSegmento::Logradouro),
        ]);

        assert_eq!(
            estruturar_segmentos(&entre_logradouros, false),
            Endereco {
                logradouro: Some("r x qd 5".to_string()),
                ..Default::default()
            }
        );
    }

    #[test]
    fn segmento_como_endereco_e_nucleo_rural_so_logradouro_sozinho() {
        // Só o núcleo rural disputa o logradouro: ele é o logradouro.
        assert_eq!(
            estruturar_segmentos(
                &criar_segmentado(vec![
                    criar_segmento("sitio mirador", TipoSegmento::NucleoRural),
                    criar_segmento("1", TipoSegmento::Numero),
                ]),
                false,
            ),
            Endereco {
                logradouro: Some("sitio mirador".to_string()),
                numero: Some("1".to_string()),
                ..Default::default()
            }
        );

        // Com logradouro na linha, ele volta a ser localidade.
        assert_eq!(
            estruturar_segmentos(
                &criar_segmentado(vec![
                    criar_segmento("r a", TipoSegmento::Logradouro),
                    criar_segmento("sitio mirador", TipoSegmento::NucleoRural),
                ]),
                false,
            ),
            Endereco {
                logradouro: Some("r a".to_string()),
                localidade: Some("sitio mirador".to_string()),
                ..Default::default()
            }
        );
    }

    #[test]
    fn segmento_como_endereco_segue_a_ordem_de_preferencia() {
        // Empreendimento é lugar: entra no logradouro e deixa a localidade livre.
        let com_localidade = criar_segmentado(vec![
            criar_segmento("cond palm", TipoSegmento::Empreendimento),
            criar_segmento("copacabana", TipoSegmento::Localidade),
        ]);
        assert_eq!(
            estruturar_segmentos(&com_localidade, false),
            Endereco {
                logradouro: Some("cond palm".to_string()),
                localidade: Some("copacabana".to_string()),
                ..Default::default()
            }
        );

        // Número em sequência não concatena: cai no complemento.
        let numero_repetido = criar_segmentado(vec![
            criar_segmento("10", TipoSegmento::Numero),
            criar_segmento("20", TipoSegmento::Numero),
        ]);
        assert_eq!(
            estruturar_segmentos(&numero_repetido, false),
            Endereco {
                numero: Some("10".to_string()),
                complemento: Some("20".to_string()),
                ..Default::default()
            }
        );

        // Logradouro depois de um cep entra no próprio campo.
        let depois_de_cep = criar_segmentado(vec![
            criar_segmento("22000-000", TipoSegmento::Cep),
            criar_segmento("r x", TipoSegmento::Logradouro),
        ]);
        assert_eq!(
            estruturar_segmentos(&depois_de_cep, false),
            Endereco {
                logradouro: Some("r x".to_string()),
                cep: Some("22000-000".to_string()),
                ..Default::default()
            }
        );
    }

    #[test]
    fn segmento_como_endereco_empilha_complemento() {
        // Complemento é concatenável: o segundo trecho entra em sequência.
        let segmentado = criar_segmentado(vec![
            criar_segmento("r x", TipoSegmento::Logradouro),
            criar_segmento("123", TipoSegmento::Numero),
            criar_segmento("apto 45", TipoSegmento::Complemento),
            criar_segmento("bloco b", TipoSegmento::Complemento),
        ]);

        assert_eq!(
            estruturar_segmentos(&segmentado, false),
            Endereco {
                logradouro: Some("r x".to_string()),
                numero: Some("123".to_string()),
                complemento: Some("apto 45 bloco b".to_string()),
                localidade: None,
                cep: None,
            }
        );
    }

    #[test]
    fn segmento_como_endereco_direciona_quilometragem() {
        // Sem número, a quilometragem vira o número.
        let sem_numero = criar_segmentado(vec![criar_segmento(
            "km 304",
            TipoSegmento::QuilometragemVia,
        )]);

        assert_eq!(
            estruturar_segmentos(&sem_numero, false),
            Endereco {
                numero: Some("km 304".to_string()),
                ..Default::default()
            }
        );

        // Com número, a quilometragem cai no complemento.
        let com_numero = criar_segmentado(vec![
            criar_segmento("r x", TipoSegmento::Logradouro),
            criar_segmento("123", TipoSegmento::Numero),
            criar_segmento("km 304", TipoSegmento::QuilometragemVia),
        ]);

        assert_eq!(
            estruturar_segmentos(&com_numero, false),
            Endereco {
                logradouro: Some("r x".to_string()),
                numero: Some("123".to_string()),
                complemento: Some("km 304".to_string()),
                ..Default::default()
            }
        );
    }

    #[test]
    fn segmento_como_endereco_sem_padronizar_mantem_os_valores() {
        let segmentado = criar_segmentado(vec![
            criar_segmento("av atlantica", TipoSegmento::Logradouro),
            criar_segmento("123", TipoSegmento::Numero),
            criar_segmento("apto 301", TipoSegmento::Complemento),
        ]);

        assert_eq!(
            segmentado.como_endereco(false),
            Endereco {
                logradouro: Some("av atlantica".to_string()),
                numero: Some("123".to_string()),
                complemento: Some("apto 301".to_string()),
                ..Default::default()
            }
        );
    }
}
