# Dashboard — Assistência Social de Jacarezinho

Sistema desenvolvido para apoio estratégico e operacional da assistência social da Prefeitura de Jacarezinho - PR.

O dashboard foi criado com foco em análise gerencial, permitindo identificar padrões de atendimento, demandas críticas e apoiar a tomada de decisão baseada em dados.

---

# Objetivo

O projeto tem como finalidade transformar dados operacionais da assistência social em informações analíticas para auxiliar gestores e equipes na identificação de:

- Demandas com maior impacto nos serviços;
- Tipos de atendimento mais recorrentes;
- Regiões com maior criticidade;
- Unidades com maior volume de atendimentos;
- Distribuição operacional das equipes;
- Tendências futuras de demanda.

Além disso, o sistema foi estruturado para possibilitar futuras implementações de modelos preditivos utilizando Machine Learning.

---

# Tecnologias Utilizadas

- Python
- Streamlit
- DuckDB
- Pandas
- Plotly

---

# Arquitetura da Solução

O projeto utiliza DuckDB como mecanismo analítico para otimizar o processamento dos dados dentro do Streamlit.

Essa abordagem foi adotada para:

- Reduzir consumo excessivo de memória RAM;
- Melhorar performance das consultas;
- Evitar travamentos na aplicação;
- Trabalhar com grandes volumes de dados de forma mais eficiente;
- Permitir consultas analíticas rápidas diretamente no dashboard.

---

# Funcionalidades

## Indicadores Gerenciais

- Total de atendimentos;
- Distribuição por tipo de atendimento;
- Evolução temporal;
- Comparativo entre unidades.

## Análise Operacional

- Identificação de atendimentos críticos;
- Monitoramento de carga operacional;
- Análise de produtividade.

## Análise Territorial

- Identificação de regiões mais impactadas;
- Mapeamento de demandas;
- Visualização de locais com maior necessidade de atendimento.

## Futuras Implementações

- Previsão de demanda;
- Machine Learning;
- Detecção de sazonalidade;
- Modelos preditivos para apoio à gestão.

---

# Privacidade dos Dados

Os dados utilizados neste projeto possuem caráter sensível e não podem ser disponibilizados publicamente.

Por esse motivo:

- Os datasets não estão incluídos neste repositório;
- Nenhuma informação pessoal é compartilhada;
- Apenas o código-fonte da aplicação está disponível;
- O uso dos dados deve respeitar a legislação vigente de proteção de dados.

---

# Estrutura do Projeto

```bash
├── app/
├── assets/
├── data/
├── queries/
├── utils/
├── app.py
├── requirements.txt
└── README.md