# 🚜 ALC-idletime: Quantificação de Ociosidade em Maquinário Agrícola

![Python](https://img.shields.io/badge/Python-3.11-blue.svg)
![Status](https://img.shields.io/badge/Status-Research_Complete-green.svg)
![License](https://img.shields.io/badge/License-MIT-lightgrey.svg)
![Institution](https://img.shields.io/badge/Institution-IFTM-red.svg)

> **Nota Acadêmica:** Este repositório contém o código-fonte e os *pipelines* de dados desenvolvidos como parte
integrante da Dissertação de Mestrado apresentada ao **Programa de Mestrado Profissional em Produção Vegetal do Instituto Federal do Triângulo Mineiro (IFTM)**.

---

## 📖 Sobre o Projeto

A modernização da agricultura gera dados massivos, mas a latência entre a coleta e a decisão ainda é um gargalo. 
Este projeto desenvolve um **Pipeline de Engenharia de Dados** determinístico para processar dados de telemetria 
de alta frequência (10 Hz), visando quantificar, classificar e mitigar o tempo ocioso (*idle time*) em frotas agrícolas mecanizadas.

O estudo utilizou o dataset público *Agricultural Load Cycles* (TUM), consolidando mais de **31 milhões de registros** 
de uma frota de tratores Fendt operando na Alemanha.

### 🎯 Objetivos Principais
1.  **Ingestão de Big Data:** Processamento de arquivos brutos heterogêneos via paralelismo.
2.  **Padronização:** Implementação de um *Canonical Dictionary* para unificar nomenclaturas de sensores (CAN Bus).
3.  **Algoritmo Físico:** Detecção de ociosidade baseada em limiares físicos de velocidade (< 0.75 m/s) e rotação do motor.
4.  **Análise Estatística:** Validação do perfil de consumo via ANOVA e Teste de Tukey.
5.  **Sustentabilidade:** Estimativa de redução de emissões de CO₂e através da eficiência operacional.

---

## 🛠️ Stack Tecnológico

O projeto foi desenvolvido em **Python 3.11**, utilizando as seguintes bibliotecas principais:

* **Pandas & NumPy:** Manipulação e álgebra de dados.
* **PyArrow:** Armazenamento colunar otimizado (Parquet) e *schema evolution*.
* **Concurrent.futures:** Processamento paralelo para leitura de arquivos (I/O bound).
* **SciPy & Statsmodels:** Análise estatística rigorosa (ANOVA, Tukey HSD).
* **Plotly Express/Graph_Objects:** Visualização de dados interativa e storytelling.

---