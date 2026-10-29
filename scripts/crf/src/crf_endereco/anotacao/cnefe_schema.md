## CNEFE (only when the SQL tool is enabled)

Base with ~110.6 million rows and ~106.4 million unique addresses
(`code_address`). Each row is a species present at the address (household,
establishment, ...), so the same address appears in several rows. Use it to
answer "what does this term mean / where is this place", never to decide a label.

- All text is UPPERCASE and WITHOUT ACCENTS. Empty text is `''` (not NULL) and a
  missing number is `0` (not NULL).
- No number: `num_adress = 0` with `dsc_modificador = 'SN'` (26 M rows). When
  `dsc_modificador = 'KM'`, `num_adress` is the kilometer. The modifier also
  holds number suffixes (A, B, CASA 2) and markers (POSTE, SUCAM): free text,
  ~157 thousand distinct values.
- There is NO bairro column. `desc_localidade` is the locality (district seat,
  village, `ZONA RURAL`, `CENTRO`, even a BR number).
- `nom_tipo_seglogr` has 390 distinct values. Most common: RUA (73 M), AVENIDA,
  ESTRADA, TRAVESSA, RODOVIA, FAZENDA, SITIO, EDF, POVOADO, ALAMEDA, BECO.
  Typical rural types: CORREGO, RAMAL, LINHA, COMUNIDADE, IGARAPE, ASSENTAMENTO.
- `nom_titulo_seglogr` is empty in 86% of rows; when filled it is the street
  title (SAO, DOUTOR, SANTA, PADRE, CORONEL...), separate from the name.
- `nom_seglogr` has ~1.28 M distinct values and can be literally
  `SEM DENOMINACAO` (1.2 M rows).
- Complements come in pairs `nom_comp_elemN`/`val_comp_elemN` (N=1..5; 1 and 2
  are common): `nom` is the category (CASA, APARTAMENTO, BLOCO, QUADRA, FUNDOS,
  FRENTE, TERREO, ANDAR, LOTE, LOJA, TORRE, EDIFICIO, CONJUNTO...), `val` is the
  value, often empty in elem1.
- `cod_especie`: 1=private household (82%), 3=agricultural establishment,
  6=establishment for other purposes, 7=building under construction.
  `dsc_estabelecimento` is the establishment name (BAR, IGREJA, 'VAGO',
  'SEM NOME'), not the street.
- `code_muni` is the 7-digit IBGE code.

Try to restrict queries by município and/or uf, always use a LIMIT and avoid
`SELECT *`.

### Table `cnefe`

```text
code_address|INTEGER          code_state|INTEGER        code_muni|INTEGER
code_district|INTEGER         code_sub_district|BIGINT  code_sector|VARCHAR
num_quadra|INTEGER            num_face|INTEGER          cep|INTEGER
desc_localidade|VARCHAR       nom_tipo_seglogr|VARCHAR  nom_titulo_seglogr|VARCHAR
nom_seglogr|VARCHAR           num_adress|INTEGER        dsc_modificador|VARCHAR
nom_comp_elem1|VARCHAR        val_comp_elem1|VARCHAR    nom_comp_elem2|VARCHAR
val_comp_elem2|VARCHAR        nom_comp_elem3|VARCHAR    val_comp_elem3|VARCHAR
nom_comp_elem4|VARCHAR        val_comp_elem4|VARCHAR    nom_comp_elem5|VARCHAR
val_comp_elem5|VARCHAR        lat|DOUBLE               lon|DOUBLE
nv_geo_coord|INTEGER          cod_especie|INTEGER       dsc_estabelecimento|VARCHAR
cod_indicador_estab_endereco|INTEGER  cod_indicador_const_endereco|INTEGER
cod_indicador_finalidade_const|INTEGER  cod_tipo_especi|INTEGER
```

### Table `municipio`

```text
cod_ibge|BIGINT   municipio|VARCHAR   uf|VARCHAR
```

### Useful DuckDB functions

```text
concat(...) / concat_ws(sep, ...)   ends_with(s, sub)   starts_with(s, sub)
contains(s, sub)                    lower(s) / upper(s)  len(s)
strip_accents(s)                    regexp_matches(s, re)
levenshtein(a, b)                   damerau_levenshtein(a, b)
jaccard(a, b)                       jaro_winkler_similarity(a, b[, cutoff])
```
