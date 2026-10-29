# Annotation examples — verbatim from the corpus

Real addresses from the dataset, copied without normalization, with the target
annotation. Each block shows the raw address and, below it, `tipo` "valor".

## Prototypical

### Complete urban address

`R CAPITAO REBELINHO 396 AP 201 EDF MARIA CECILIA`

→ `logradouro` "R CAPITAO REBELINHO" · `numero` "396" · `complemento` "AP 201" · `empreendimento` "EDF MARIA CECILIA"

`PASS SAO RAIMUNDO, 30A CONJ.PANORAMA XXI. CABANAGEM. 66625-670 Belém - PA.`

→ `logradouro` "PASS SAO RAIMUNDO" · `numero` "30A" · `empreendimento` "CONJ.PANORAMA XXI" · `localidade` "CABANAGEM" · `cep` "66625-670" · `municipio` "Belém" · `uf` "PA"

### Number: glued suffix and range

`R ALM TAMANDARE 49 B AO LADO DA LAGOA`

→ `logradouro` "R ALM TAMANDARE" · `numero` "49 B" · `referencia` "AO LADO DA" · `recurso_natural` "LAGOA"

`AV VENEZUELA 232 A 264 DA QUADRA 20`

→ `logradouro` "AV VENEZUELA" · `numero` "232 A 264" · `parcela` "QUADRA 20"

### Whole complement (never cut)

`AV SAGITARIO 138 CJ 310A - TORRE 1 - ALPHA SQUARE`

→ `logradouro` "AV SAGITARIO" · `numero` "138" · `complemento` "CJ 310A - TORRE 1" · `empreendimento` "ALPHA SQUARE"

`AV TUCUNS S/N BREEZES BUZIOS RESORT - BL 09 - APTO 102`

→ `logradouro` "AV TUCUNS" · `numero` "S/N" · `empreendimento` "BREEZES BUZIOS RESORT" · `complemento` "BL 09 - APTO 102"

### Parcela (land chain in one span)

`LOTE 01 GLEBA 01 COLONIA BOA VENTURA`

→ `parcela` "LOTE 01" · `parcela` "GLEBA 01" · `nucleo_rural` "COLONIA BOA VENTURA"

### Rural nucleus: village, settlement, farm

`POVOADO AGUA PRETA, 65495-000 Miranda do Norte - MA.`

→ `nucleo_rural` "POVOADO AGUA PRETA" · `cep` "65495-000" · `municipio` "Miranda do Norte" · `uf` "MA"

`SITIO CANTINHO DA ESPERANCA, Q. 0, L. 5  ,ASSENTAMENTO N.SRA. DA ABADIA`

→ `nucleo_rural` "SITIO CANTINHO DA ESPERANCA" · `parcela` "Q. 0, L. 5" · `nucleo_rural` "ASSENTAMENTO N.SRA. DA ABADIA"

### Natural feature (in any position)

`RIO TOCANTINS S/N COMUNIDADE BOA VIDA`

→ `recurso_natural` "RIO TOCANTINS" · `numero` "S/N" · `nucleo_rural` "COMUNIDADE BOA VIDA"

`MARGEM ESQUERDA DO RIO PARAGUAI`

→ `referencia` "MARGEM ESQUERDA DO" · `recurso_natural` "RIO PARAGUAI"

`AV TROPICAL S/N MARGEM DO RIO TAPAJOS`

→ `logradouro` "AV TROPICAL" · `numero` "S/N" · `referencia` "MARGEM DO" · `recurso_natural` "RIO TAPAJOS"

### Reference: only the marker; the name keeps its own type

`R GASPAR NEVES 11 ESQUINA COM RUA HILARIO VIEIRA`

→ `logradouro` "R GASPAR NEVES" · `numero` "11" · `referencia` "ESQUINA COM" · `logradouro` "RUA HILARIO VIEIRA"

`SRV DE ACESSO A PRAIA S/N PERTO DO CLUBE`

→ `logradouro` "SRV DE ACESSO A PRAIA" · `numero` "S/N" · `referencia` "PERTO DO" · `ponto_referencia` "CLUBE"

### A connective between two referents is also `referencia`

`AV PEDRO ALVARES CABRAL 307 ENTRE AV V S FRANCO E TV D R COELHO`

→ `logradouro` "AV PEDRO ALVARES CABRAL" · `numero` "307" · `referencia` "ENTRE" · `logradouro` "AV V S FRANCO" · `referencia` "E" · `logradouro` "TV D R COELHO"

### A number after a reference is `numero`

`R ARISTIDES REGO S/N AO LADO DO N 33`

→ `logradouro` "R ARISTIDES REGO" · `numero` "S/N" · `referencia` "AO LADO DO" · `numero` "N 33"

### Denomination: the marker opens, the name is `logradouro`

`R JOAO CARREIRO JUNIOR ANTIGA RUA F 98`

→ `logradouro` "R JOAO CARREIRO JUNIOR" · `denominacao` "ANTIGA" · `logradouro` "RUA F" · `numero` "98"

`RUA BALTAZAR MARINHO, CENTRO, 529, ANTIGA RUA DO CAJUEIRO, MACAÍBA, RN`

→ `logradouro` "RUA BALTAZAR MARINHO" · `localidade` "CENTRO" · `numero` "529" · `denominacao` "ANTIGA" · `logradouro` "RUA DO CAJUEIRO" · `municipio` "MACAÍBA" · `uf` "RN"

### Highway code and kilometer

`BR 364 SENTIDO NOVA ARACATUBA BANCO DA TERRA`

→ `logradouro` "BR 364" · `referencia` "SENTIDO" · `ponto_referencia` "NOVA ARACATUBA" · `localidade` "BANCO DA TERRA"

`ROD Augusto Montenegro, Km 07 s/n`

→ `logradouro` "ROD Augusto Montenegro" · `quilometragem_via` "Km 07" · `numero` "s/n"

### Registration code and measurement

`EST VEREADOR BENEDITO ADELINO 2331 LOTE 21 RI 16.282`

→ `logradouro` "EST VEREADOR BENEDITO ADELINO" · `numero` "2331" · `parcela` "LOTE 21" · `cadastro` "RI 16.282"

`02 HA DO LOTE 471 GLEBA 04 PIC ALEX GUSMAO`

→ `outros` "02 HA" · `parcela` "LOTE 471 GLEBA 04" · `localidade` "PIC ALEX GUSMAO"

### DF sector

`Q SQN 302 BLOCO B 603 apartamento 603`

→ `ruido` "Q" · `logradouro` "SQN 302 BLOCO B" · `numero` "603" · `complemento` "apartamento 603"

### Palmas, outside the Plano Diretor

`RUA T 2 QD 02, 07 SANTA FE. 77064-566 Palmas - TO.`

→ `logradouro` "RUA T 2" · `parcela` "QD 02" · `numero` "07" · `localidade` "SANTA FE" · `cep` "77064-566" · `municipio` "Palmas" · `uf` "TO"

## Edge cases

### Bare head, no name

`CENTRINHO 1, S/N POVOADO. ZONA RURAL. 65279-000 Presidente Médici - MA.`

→ `localidade` "CENTRINHO 1" · `numero` "S/N" · `ruido` "POVOADO" · `localidade` "ZONA RURAL" · `cep` "65279-000" · `municipio` "Presidente Médici" · `uf` "MA"

### Inverted order: the text wins

`RU SAO PAULO 00317 FORTALEZA CENTRO CE`

→ `logradouro` "RU SAO PAULO" · `numero` "00317" · `municipio` "FORTALEZA" · `localidade` "CENTRO" · `uf` "CE"

### Stray marker before the real name

`AV Avenida Marechal Rondon s/n Esquina Travessa Prof. Luis Barbosa`

→ `ruido` "AV" · `logradouro` "Avenida Marechal Rondon" · `numero` "s/n" · `referencia` "Esquina" · `logradouro` "Travessa Prof. Luis Barbosa"

### `ANT` with no name after it

`AV BRASIL 1455 Antigo 1559`

→ `logradouro` "AV BRASIL" · `numero` "1455" · `outros` "Antigo 1559"

`R CRISOLITO 141 CASA 2 ANT LT 7 E 8 LOT SITIO PORTINHO`

→ `logradouro` "R CRISOLITO" · `numero` "141" · `complemento` "CASA 2" · `outros` "ANT" · `parcela` "LT 7 E 8" · `empreendimento` "LOT SITIO PORTINHO"

### Content with no type of its own → `outros`, reason in the comment

`RUA IZIDORA LOPES, SN ESCOLA. CENTRO. 65465-000 Cantanhede - MA.`

→ `logradouro` "RUA IZIDORA LOPES" · `numero` "SN" · `outros` "ESCOLA" · `localidade` "CENTRO" · `cep` "65465-000" · `municipio` "Cantanhede" · `uf` "MA"

## Counter-examples (the cut that is NOT made)

- `ANTIGA RUA B` is **not** one segment: `denominacao` "ANTIGA" + `logradouro` "RUA B".
- `ENTRE RUA A E RUA B` does **not** swallow the `E`: `referencia` "ENTRE" · `logradouro` "RUA A" · `referencia` "E" · `logradouro` "RUA B".
- `AO LADO DO N 33` does **not** put the number inside the reference: `referencia` "AO LADO DO" + `numero` "N 33".
- `BL 09 APTO 102` is **not** two complements.
- `100 A` is **not** `numero` "100" + `complemento` "A".
- `SITIO MIRADOR`, `FAZENDA SANTA RITA`, `RIO TOCANTINS` are **not** `logradouro` — they go to `nucleo_rural` / `recurso_natural`.
- `RIO DE JANEIRO`, `RIO BRANCO` are `municipio`/`uf`, not `recurso_natural`.
- `VILA HUMBERTO` is `localidade` (urban bairro), not `nucleo_rural`.
- `CHACARA 51` is `parcela`; `SITIO BOA VISTA` is `nucleo_rural`.
- `RUA APAE` is `logradouro` (way name), not `empreendimento`.
- `Q.`, `L.`, `GLE.` are **not** `ruido`: they are the abbreviated `parcela` heads (`RUA SEM NOME, Q. - GLEBA A1, L. - BL 38`).
- `Av: Hilton Souto Maior` / `Rua: José Lemes Bugre` are **not** `ruido:"Av:"` + name: the colon belongs to the way name, so each is one `logradouro`.
- `PA 124` is `logradouro` (Pará state highway); `PA 44191` in a federal property in RJ is `cadastro`; `NR 03` after the number is `complemento`.
