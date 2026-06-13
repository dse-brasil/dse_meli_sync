# DSE Meli Sync

![Versão](https://img.shields.io/badge/vers%C3%A3o-v1.0.0-blueviolet)

O **DSE Meli Sync** é um sistema inteligente de alta performance e resiliência projetado para sincronização de dados em tempo real e automação de atendimento de vendas no **Mercado Livre**. O core do sistema conta com o **Robô Especialista em Vendas**, um agente de Inteligência Artificial conversacional focado em conversão de vendas, quebras de objeções e análise de métricas no modelo de dropshipping de produtos digitais e físicos relevantes.

Desenvolvido pela **Data Science Enthusiasts (DSE)**.

---

## 🏗️ Arquitetura do Sistema

O sistema foi desenhado sob uma arquitetura orientada a eventos para garantir baixíssima latência na resposta de webhooks do Mercado Livre e isolamento das chamadas pesadas de IA.

```
                  ┌───────────────────────────┐
                  │   Mercado Livre Webhook   │
                  └─────────────┬─────────────┘
                                │ HTTP POST
                                ▼
                  ┌───────────────────────────┐
                  │       FastAPI App         │
                  └──────┬─────────────┬──────┘
                         │             │
        Grava Payload    │             │ Enfileira Evento
        Bruto (JSONB)    ▼             ▼
                  ┌──────────┐   ┌───────────┐
                  │PostgreSQL│   │Redis Queue│
                  └──────────┘   └─────┬─────┘
                                       │
                                       ▼
                                 ┌───────────┐
                                 │Celery task│
                                 └─────┬─────┘
                                       │
                    ┌──────────────────┴──────────────────┐
                    ▼                                     ▼
          ┌──────────────────┐                  ┌──────────────────┐
          │   Prompt Guard   │                  │  Mercado Livre   │
          │  (AES-GCM + Check│                  │  API / Respostas │
          └─────────┬────────┘                  └──────────────────┘
                    │
                    ▼
          ┌──────────────────┐
          │  OpenAI / Gemini │
          └──────────────────┘
```

1. **FastAPI Gateway**: Ponto de entrada assíncrono para os Webhooks do Mercado Livre. O webhook valida a assinatura do cabeçalho, persiste o payload bruto em formato `JSONB` no PostgreSQL e delega o processamento pesado enviando um job para a fila do Redis. Retorna `200 OK` em milissegundos.
2. **PostgreSQL**: Banco relacional que usa campos nativos `JSONB` para manter a integridade histórica dos webhooks brutos do Mercado Livre.
3. **Redis & Celery**: Broker de mensageria e gerenciador de filas para processamento em background, evitando concorrência excessiva e garantindo retry automático em falhas de chamadas externas.
4. **Camada de Segurança de Prompt (Guardrails)**:
   - **Criptografia Simétrica (AES-GCM)**: O Prompt Master do robô é descriptografado apenas em memória no início da execução da tarefa utilizando chaves injetadas em ambiente seguro.
   - **Detecção de Jailbreak**: Heurísticas e validações de input que impedem comandos de override do comportamento do robô.
   - **Leak Prevention (Guardrail de Saída)**: Validação na saída gerada para garantir que o prompt interno do sistema nunca seja vazado na resposta.

---

## 🛠️ Stack Tecnológica

- **Linguagem**: Python 3.10+
- **Framework Web**: FastAPI
- **Banco de Dados**: PostgreSQL (SQLAlchemy Async / Alembic)
- **Mensageria & Filas**: Celery + Redis
- **Segurança**: Cryptography (AES-GCM) para segurança de chaves e Guardrails customizados.
- **Orquestração**: Docker & Docker Compose

---

## 🚀 Como Executar

### Pré-requisitos
- Docker e Docker Compose instalados.

### Passos para Configuração

1. Clone o repositório:
   ```bash
   git clone https://github.com/dse-brasil/dse_meli_sync.git
   cd dse_meli_sync
   ```

2. Crie e configure o arquivo `.env`:
   ```bash
   cp .env.example .env
   ```
   *Preencha as variáveis de ambiente necessárias, incluindo a chave secreta para decodificação do prompt (`PROMPT_DECRYPTION_KEY`) e as credenciais do Mercado Livre/LLM.*

3. Suba o ambiente utilizando Docker Compose:
   ```bash
   docker-compose up --build
   ```

4. Acesse a documentação interativa da API:
   - Swagger UI: `http://localhost:8000/docs`
   - Redoc: `http://localhost:8000/redoc`

---

## 🔒 Proteção do Prompt Master e Segurança

Para evitar ataques de *Prompt Injection* ou engenharia social reversa para descobrir as diretrizes do robô, o **DSE Meli Sync** implementa:

1. **Descriptografia In-Memory**: O prompt do robô não reside em arquivos de configuração estáticos do código ou texto puro no banco de dados. Ele é mantido criptografado e carregado na inicialização da aplicação em background.
2. **Heurística de Entrada**: Um analisador de comandos detecta tentativas comuns de jailbreak.
3. **Validador de Saída**: O resultado gerado pelo LLM é processado por um scanner de regex para verificar se houve citação direta a termos de diretrizes privadas antes de enviar a resposta de volta ao Mercado Livre.

---

## 👥 Colaboradores

Atualmente, o projeto é mantido e desenvolvido por:
* **Fernando Torres Ferreira Silva** ([@fertorresfs](https://github.com/fertorresfs)) — Idealizador e desenvolvedor ativo, responsável pela arquitetura do bot, integração de RAG, segurança e painel administrativo web.

---

## ⚖️ Licença

Este projeto é de uso interno e educacional da comunidade **Data Science Enthusiasts (DSE)**. Consulte as políticas internas de contribuição antes de realizar pull requests.
