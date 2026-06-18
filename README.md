# Gedgov — Inteligência Orçamentária para Prefeituras

Micro-SaaS que ingere dados públicos (convênios do **Portal da Transparência/CGU** e
entregas fiscais do **Siconfi/Tesouro Nacional**) para um Postgres na nuvem e os exibe
em um dashboard executivo (Flask, hospedado na Vercel).

## Arquitetura

```
src/                      Camada de ingestão (rodar localmente ou em job agendado)
  config.py               CIDADES (carteira) + get_conn() (lê DATABASE_URL)
  main.py                 Orquestrador: cria tabelas + dispara as ingestões
  ingestao_transferegov.py  Convênios da CGU -> raw_transferegov
  ingestao_siconfi.py     Entregas fiscais do Siconfi (todas as cidades) -> raw_siconfi_entregas
api/                      Dashboard Flask (deploy na Vercel)
  index.py                Lê o banco e renderiza
  templates/index.html
gerador_relatorio.py      Relatório executivo com IA (Gemini) -> HTML/PDF
```

## Variáveis de ambiente

Todas as credenciais vêm de variáveis de ambiente — **nada é hardcoded**.
Copie `.env.example` para `.env` e preencha:

| Variável         | Onde é usada                | Descrição                                              |
|------------------|-----------------------------|--------------------------------------------------------|
| `DATABASE_URL`   | API + ingestão + relatório  | Connection string completa do Postgres (Neon)          |
| `CGU_API_KEY`    | ingestão Transferegov       | Chave da API do Portal da Transparência                |
| `GEMINI_API_KEY` | gerador de relatório        | Chave do Google Gemini                                 |

> ⚠️ **Segurança:** as credenciais antigas foram removidas do código, mas **ainda estão no
> histórico do Git**. Rotacione-as (gere novas) nos painéis do **Neon**, do
> **Portal da Transparência** e do **Google AI Studio**. Trocar no código não basta.

## Rodando localmente

### Ingestão
```bash
pip install -r requirements-ingestion.txt
# preencha o .env com DATABASE_URL e CGU_API_KEY
python src/main.py
```

### Dashboard
```bash
pip install -r requirements.txt
# DATABASE_URL precisa estar no ambiente
python api/index.py
```

## Deploy na Vercel

A Vercel empacota apenas a pasta `api/` e usa `requirements.txt` (sem as deps pesadas de
ingestão/relatório). Configure a variável `DATABASE_URL` em
**Project Settings → Environment Variables** no painel da Vercel.
