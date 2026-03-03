// ====== Funções Públicas =======

/// Padroniza CEPs em formato numérico para uma string formatada.
///
/// Completa com zeros à esquerda, caso necessário, e retorna erro se o valor numérico
/// for maior do que o tamanho permitido para CEPs.
///
/// # Exemplo
/// ```
/// use enderecobr_rs::padronizar_cep_numerico;
/// let cep = padronizar_cep_numerico(123456);
/// assert_eq!(cep, Ok("00123-456".to_string()));
/// ```
///
pub fn padronizar_cep_numerico(valor: i32) -> Result<String, String> {
    if valor >= 99999999 {
        return Err("CEP com muitos dígitos".to_string());
    }
    let cep = format!("{:08}", valor);
    Ok(format!("{}-{}", &cep[0..5], &cep[5..8]))
}

/// Padroniza CEPs em formato textual para uma string formatada, retornando possíveis erros.
///
/// Esta função ignora quaisquer caracteres de pontuação, além de completar com zeros à esquerda quando necessário.
///
/// # Exemplo
/// ```
/// use enderecobr_rs::padronizar_cep;
/// let cep = padronizar_cep("12345-6");
/// assert_eq!(cep, Ok("00123-456".to_string()));
///
/// let cep_grande = padronizar_cep("123456789");
/// assert_eq!(cep_grande, Err("CEP com muitos dígitos".to_string()));
///
/// let cep_invalido = padronizar_cep("123456e");
/// assert_eq!(cep_invalido, Err("CEP com caracteres inválidos".to_string()));
/// ```
///
pub fn padronizar_cep(valor: &str) -> Result<String, String> {
    if valor
        .chars()
        .any(|c| !c.is_ascii_punctuation() && !c.is_numeric() && !c.is_whitespace())
    {
        return Err("CEP com caracteres inválidos".to_string());
    }

    if valor.trim().is_empty() {
        return Ok("".to_string());
    }

    let valor_numerico: String = valor.chars().filter(|c| c.is_numeric()).collect();

    if valor_numerico.len() > 8 {
        return Err("CEP com muitos dígitos".to_string());
    }

    // Padding na esquerda
    let cep = format!("{:0>8}", valor_numerico);
    Ok(format!("{}-{}", &cep[0..5], &cep[5..8]))
}

/// Converte uma string de CEP em um número inteiro, removendo caracteres não numéricos.
///
/// Extrai até 8 dígitos numéricos consecutivos do início da string fornecida e tenta
/// convertê-los em um valor `u32`. Retorna `None` se a string não contiver dígitos
/// suficientes ou se a conversão falhar.
///
/// # Exemplo
/// ```
/// use enderecobr_rs::cep::cep_para_numero;
/// assert_eq!(cep_para_numero("01234567"), Some(1234567));
/// assert_eq!(cep_para_numero("01.234-567"), Some(1234567));
/// assert_eq!(cep_para_numero("abc"), None);
/// assert_eq!(cep_para_numero("000000"), Some(0));
/// ```
pub fn cep_para_numero(cep: &str) -> Option<u32> {
    let cep_num: String = cep.chars().filter(|c| c.is_numeric()).take(8).collect();
    cep_num.parse().ok()
}

/// Padroniza CEPs em formato textual para uma string formatada, tentando corrigir possíveis erros.
///
/// Esta função ignora quaisquer caracteres não numéricos, além de remover números extras e completar com zeros à
/// esquerda quando necessário.
///
/// # Exemplo
/// ```
/// use enderecobr_rs::padronizar_cep_leniente;
/// let cep = padronizar_cep_leniente("a123b45  6");
/// assert_eq!(cep, "00123-456".to_string());
/// ```
///
pub fn padronizar_cep_leniente(valor: &str) -> String {
    if valor.is_empty() {
        return "".to_string();
    }

    let valor_numerico: String = valor.chars().filter(|c| c.is_numeric()).take(8).collect();

    // Padding na esquerda
    let cep = format!("{:0>8}", valor_numerico);
    format!("{}-{}", &cep[0..5], &cep[5..8])
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn erro_quando_cep_contem_letra() {
        let erro_esperado = Err("CEP com caracteres inválidos".to_string());

        assert_eq!(padronizar_cep("botafogo"), erro_esperado);
        assert_eq!(padronizar_cep("oie"), erro_esperado);
        assert_eq!(padronizar_cep("hehe"), erro_esperado);
    }

    #[test]
    fn erro_quando_cep_contem_mais_de_8_digitos() {
        let erro_esperado = Err("CEP com muitos dígitos".to_string());

        assert_eq!(padronizar_cep_numerico(100000000), erro_esperado);
        assert_eq!(padronizar_cep("222290-140"), erro_esperado);
    }

    #[test]
    fn padroniza_corretamente() {
        assert_eq!(padronizar_cep("22290-140").unwrap(), "22290-140");
        assert_eq!(padronizar_cep("22290 140").unwrap(), "22290-140");
        assert_eq!(padronizar_cep("22290- 140").unwrap(), "22290-140");
        assert_eq!(padronizar_cep("22.290-140").unwrap(), "22290-140");
        assert_eq!(padronizar_cep(" 22290  140 ").unwrap(), "22290-140");
        assert_eq!(padronizar_cep("01000-000").unwrap(), "01000-000");
        assert_eq!(padronizar_cep("1000000").unwrap(), "01000-000");
        assert_eq!(padronizar_cep(" 1000000").unwrap(), "01000-000");

        // Teste novo
        assert_eq!(padronizar_cep("   ").unwrap(), "");
    }

    #[test]
    fn testa_cep_para_numero() {
        assert_eq!(cep_para_numero("12345678"), Some(12345678));
        assert_eq!(cep_para_numero("12345"), Some(12345));
        assert_eq!(cep_para_numero("12-345.678"), Some(12345678));
        assert_eq!(cep_para_numero(""), None);
        assert_eq!(cep_para_numero("abcdefg"), None);
        assert_eq!(cep_para_numero("00000000"), Some(0));
    }
}
