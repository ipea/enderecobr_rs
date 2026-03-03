DIR_DADOS = ./dados
DIR_BRUTOS = ./dados/brutos
DIR_INTERMEDIARIOS = ./dados/intermediarios
DIR_SNAPSHOTS = ./dados/snapshot_test
DIR_SQLS = ./sql
HF_DATASET = galmeida/enderecobr_rs

SNAPSHOT_BASE_URL = https://huggingface.co/datasets/galmeida/enderecobr_rs/resolve/main/snapshot_test

SNAPSHOT_FILES = complemento_bruto.csv complemento_snapshot.csv localidade_bruto.csv localidade_snapshot.csv logradouro_bruto.csv logradouro_snapshot.csv municipio_bruto.csv municipio_snapshot.csv numero_bruto.csv numero_snapshot.csv uf_bruto.csv uf_snapshot.csv

.PHONY: hf-publicar-dataset hf-publicar-snapshot-test snapshot-criar-bruto snapshot-download

### Envio para o HF Hub

hf-publicar-dataset:
	hf upload $(HF_DATASET) --repo-type=dataset --commit-message "feat: Atualiza dataset básico de endereços" dados/dataset.parquet train.parquet
	hf upload $(HF_DATASET) --repo-type=dataset --commit-message "doc: Atualiza README" README_HF.md README.md

hf-publicar-snapshot-test:
	hf upload $(HF_DATASET) --repo-type=dataset --commit-message "feat: Atualiza arquivos do teste de snapshot" $(DIR_SNAPSHOTS) snapshot_test/

### Download Brutos

# Variável '$@' indica o nome do target.

$(DIR_BRUTOS)/cno.zip:
	curl -o $@ 'https://arquivos.receitafederal.gov.br/dados/cno/cno.zip'

$(DIR_BRUTOS)/cneas.csv:
	curl -o $@ 'https://aplicacoes.mds.gov.br/sagi/servicos/misocial_mes_equipamento/?fl=codigo_ibge%2Canomes_s%20cneas_entidade_nome_municipio_s%20cneas_entidade_sigla_uf_s%20cneas_cod_entidade_s%20cneas_entidade_numero_cnpj_s%20cneas_entidade_razao_social_s%20cneas_entidade_nome_fantasia_s%20cneas_entidade_endereco_logradouro_s%20cneas_entidade_endereco_numero_s%20cneas_entidade_endereco_complemento_s%20cneas_entidade_endereco_bairro_s%20cneas_entidade_endereco_cep_s%20cneas_entidade_situacao_cadastro_s%20cneas_entidade_dt_extracao_s&fq=cneas_cod_entidade_s%3A*&q=*%3A*&rows=100000&sort=anomes_s%20desc%2C%20codigo_ibge%20asc&wt=csv&fq=anomes_s:2025*'

$(DIR_BRUTOS)/cnes.zip:
	curl -o $@ 'https://s3.sa-east-1.amazonaws.com/ckan.saude.gov.br/CNES/cnes_estabelecimentos_csv.zip'

$(DIR_BRUTOS)/censo_escolar.zip:
	curl -o $@ 'https://download.inep.gov.br/dados_abertos/microdados_censo_escolar_2024.zip'

$(DIR_BRUTOS)/postos_cadunico.csv:
	curl -o $@ 'https://aplicacoes.mds.gov.br/sagi/servicos/equipamentos?fq=tipo_equipamento:POSTO_CADASTRAMENTO&wt=csv&fl=id_equipamento,ibge,uf,cidade,nome,responsavel,telefone,endereco,numero,complemento,referencia,bairro,cep,georef_location,data_atualizacao&rows=999999999&q=*:*'

$(DIR_BRUTOS)/municipios_cnpj.csv:
	curl -o $@ 'https://www.gov.br/receitafederal/dados/municipios.csv'

### Parquets intermediários

# Variável '$<' indica a primeira dependência.

$(DIR_INTERMEDIARIOS)/cneas.parquet: $(DIR_SQLS)/cneas.sql $(DIR_BRUTOS)/cneas.csv
	duckdb < $<

$(DIR_INTERMEDIARIOS)/cno.parquet: $(DIR_SQLS)/cno.sql $(DIR_BRUTOS)/cno.zip
	duckdb < $<

$(DIR_INTERMEDIARIOS)/cnes.parquet: $(DIR_SQLS)/cnes.sql $(DIR_BRUTOS)/cnes.zip
	duckdb < $<

$(DIR_INTERMEDIARIOS)/censo_escolar.parquet: $(DIR_SQLS)/censo_escolar.sql $(DIR_BRUTOS)/censo_escolar.zip
	duckdb < $<

$(DIR_INTERMEDIARIOS)/postos_cadunico.parquet: $(DIR_SQLS)/postos_cadunico.sql $(DIR_BRUTOS)/postos_cadunico.csv
	duckdb < $<

$(DIR_INTERMEDIARIOS)/municipios_cnpj.parquet: $(DIR_SQLS)/municipios_cnpj.sql $(DIR_BRUTOS)/municipios_cnpj.csv
	duckdb < $<

# TODO: baixar dados do CNEFE em vez de usar os locais

$(DIR_INTERMEDIARIOS)/cnefe.parquet: $(DIR_SQLS)/cnefe.sql
	duckdb < $<

# TODO: baixar dados do CNPJ em vez de usar os locais

$(DIR_INTERMEDIARIOS)/cnpj.parquet: $(DIR_SQLS)/cnpj.sql $(DIR_INTERMEDIARIOS)/municipios_cnpj.parquet
	duckdb < $<

### Dataset final

$(DIR_DADOS)/dataset.parquet: $(DIR_SQLS)/dataset_total.sql $(DIR_INTERMEDIARIOS)/cneas.parquet $(DIR_INTERMEDIARIOS)/cno.parquet $(DIR_INTERMEDIARIOS)/cnes.parquet $(DIR_INTERMEDIARIOS)/censo_escolar.parquet $(DIR_INTERMEDIARIOS)/postos_cadunico.parquet $(DIR_INTERMEDIARIOS)/cnefe.parquet $(DIR_INTERMEDIARIOS)/cnpj.parquet
	duckdb < $<

### Cria arquivos simplificados para os testes de snapshot

# Quando mando criar um arquivo específico do snapshot, dou preferência para baixar
# em vez de construir baseado no dataset.
$(DIR_SNAPSHOTS)/%.csv:
	curl --location -o $@ $(SNAPSHOT_BASE_URL)/$*.csv?download=true

# Download de todos os snapshots, baseado no target anterior (by ChatGPT).
snapshot-download: $(SNAPSHOT_FILES:%=$(DIR_SNAPSHOTS)/%)

# Força criação do novo dataset de snapshot.
snapshot-criar-bruto:
	duckdb < $(DIR_SQLS)/snapshot_test_bruto.sql

### Datasets do CNEFE do Geocodebr

$(DIR_BRUTOS)/logr_cep_loc.parquet:
	curl --location -o $@ "https://github.com/ipeaGIT/padronizacao_cnefe/releases/download/v0.4.1/municipio_logradouro_cep_localidade.parquet"
