# 🚜 ALC-idletime: Quantificação de Ociosidade em Maquinário Agrícola

![Python](https://img.shields.io/badge/Python-3.11-blue.svg)
![Status](https://img.shields.io/badge/Status-Research_Complete-green.svg)
![License](https://img.shields.io/badge/License-MIT-lightgrey.svg)
![Institution](https://img.shields.io/badge/Institution-IFTM-red.svg)

---
🚜 ALC-idletime: Sistema de Auditoria de Telemetria Agrícola
Nota Acadêmica: Este software é o Produto Técnico Tecnológico desenvolvido no âmbito da Dissertação de Mestrado apresentada ao Programa de Mestrado Profissional em Produção Vegetal do Instituto Federal do Triângulo Mineiro (IFTM).

Autor: Daniel Abreu, Cientista de Dados Sênior & Mestrando.

📖 Sobre o Produto
O ALC-idletime é uma aplicação web de Engenharia de Dados e Auditoria Visual projetada para transformar dados brutos de telemetria agrícola em inteligência operacional.

Diferente de soluções de mercado que operam como "caixa preta", este sistema implementa uma abordagem determinística e auditável (White-box AI) para a classificação de ociosidade em frotas mecanizadas. A ferramenta processa dados de alta frequência (CAN Bus), aplica regras físicas de detecção de paradas e oferece uma interface Human-in-the-loop para que especialistas validem e reclassifiquem eventos (ex: distinguir "Desperdício" de "Ócio Necessário").

O sistema foi validado com o dataset Agricultural Load Cycles (TUM), processando +31 milhões de registros de tratores Fendt em operações reais na Alemanha.

🚀 Funcionalidades Chave
1. Motor de Processamento (Backend)
Ingestão Massiva: Pipeline otimizado com PyArrow para leitura paralela de arquivos de telemetria heterogêneos.

Algoritmo Físico: Detecção automática de ociosidade baseada em vetores de estado (Velocidade < 0.75 m/s & Motor Ativo & Implemento Inativo).

Padronização Canônica: Unificação automática de tags de sensores de diferentes modelos de máquinas.

2. Interface de Auditoria (Frontend)
Dashboard de Eficiência (Aba 1):

Visualização geoespacial de alta performance (via Pydeck/WebGL) capaz de renderizar milhões de pontos.

Mapa de calor 3D identificando "zonas quentes" de desperdício de combustível.

KPIs dinâmicos de consumo e emissões de CO₂.

Módulo de Replay & Reclassificação (Aba 2):

Ferramenta de Auditoria Visual sobre imagens de satélite (Google/ESRI).

Navegação temporal por slots (ex: blocos de 15 min) para análise de micromovimentos.

Funcionalidade de Reclassificação Contextual, permitindo ao agrônomo corrigir falsos positivos do algoritmo baseado no contexto visual (ex: abastecimento, manutenção).

Facilmente adaptável para outras bases telemétricas com edição dos notebooks de pre e pós processamento de dados brutos.

🛠️ Arquitetura e Tecnologias
O projeto utiliza uma arquitetura moderna de Data Science, priorizando performance em hardware local (Edge Computing):

Linguagem: Python 3.11

Interface Web: Streamlit (Single Page Application)

Geospatial Engines:

Pydeck: Renderização volumétrica em GPU.

Folium: Mapas interativos para auditoria detalhada.

Data Engineering:

Pandas/NumPy: Processamento vetorizado.

Parquet: Persistência colunar de alta compressão.

Estatística: SciPy & Statsmodels (Validação ANOVA/Tukey).

📂 Estrutura do Repositório
Esta estrutura reflete o pacote de registro de software junto ao INPI:

Bash
├── app/                  # Código-fonte da Interface (Frontend)
│   ├── app.py            # Entry point da aplicação Streamlit
│   └── .streamlit/       # Configurações de tema e servidor
│
├── src/                  # Módulos de Processamento (Backend)
│   ├── data_ingestion.py # Pipeline de leitura e limpeza
│   ├── processing.py     # Regras de negócio e física
│   └── visualization.py  # Helpers gráficos
│
├── notebooks/            # Memorial de Cálculo e EDA (Metodologia)
│   ├── 01_ingest.ipynb   # Exploração inicial
│   └── 02_analysis.ipynb # Validação estatística
│
├── main.py               # Script orquestrador
├── requirements.txt      # Dependências do projeto
└── README.md             # Documentação
⚙️ Instalação e Execução
Para rodar a ferramenta de auditoria localmente:

Clone o repositório:
Bash
https://github.com/DTech1234/ALC-idletime
cd alc-idletime

Instale as dependências:
Bash
pip install -r requirements.txt

Execute a aplicação:
Bash
streamlit run app/app.py
O sistema abrirá automaticamente em seu navegador padrão (http://localhost:8501).

📄 Licença e Citação
Este projeto está licenciado sob a licença MIT. Para uso acadêmico, favor citar:

ABREU, Daniel. QUANTIFICAÇÃO DO POTENCIAL DE REDUÇÃO DE EMISSÕES E CUSTOS POR MEIO DA OTIMIZAÇÃO DO TEMPO OCIOSO DE TRATORES AGRÍCOLAS: UMA ANÁLISE BASEADA EM DADOS DE TELEMETRIA DE ACESSO PÚBLICO. 2026. Dissertação (Mestrado Profissional em Produção Vegetal) - Instituto Federal do Triângulo Mineiro, Uberaba.
