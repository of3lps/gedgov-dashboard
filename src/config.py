"""Configuração compartilhada da camada de ingestão.

Centraliza a carteira de clientes (CIDADES) e a conexão com o banco, lendo
credenciais sempre de variáveis de ambiente (nunca hardcoded).
"""
import os

import psycopg2

try:
    # Carrega o .env automaticamente quando rodando localmente.
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    # python-dotenv é opcional (não é necessário em produção, onde as env vars
    # já vêm do ambiente). Seguimos sem ele se não estiver instalado.
    pass

# A carteira de clientes do SaaS (código IBGE -> nome de exibição).
CIDADES = {
    "3523206": "Itararé / SP",
    "3145059": "Nova Porteirinha / MG",
    "5107602": "Rondonópolis / MT",
    "5102702": "Canarana / MT",
    "5107065": "Querência / MT",
    "5100201": "Água Boa / MT",
    "2305605": "Independência / CE",
    "2301109": "Aracati / CE",
    "3159605": "Santa Rita do Sapucaí / MG",
    "3510500": "Caraguatatuba / SP",
}


def get_conn():
    """Abre uma conexão com o Postgres usando a env var DATABASE_URL.

    DATABASE_URL deve ser a connection string completa do banco (ex.: Neon).
    """
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError(
            "DATABASE_URL não definida. Configure a variável de ambiente "
            "(veja .env.example) antes de rodar a ingestão."
        )
    return psycopg2.connect(database_url)
