#!/usr/bin/env python3
"""
Cria ou atualiza um usuário no banco de dados do Gedgov.

Uso:
    python criar_usuario.py <username> <senha> [codigo_ibge] [--admin]

Exemplos:
    # Usuário admin (vê todas as prefeituras)
    python criar_usuario.py admin senha123 --admin

    # Usuário de uma prefeitura específica
    python criar_usuario.py itarare.sp senha123 3523206

    # Trocar senha de um usuário existente
    python criar_usuario.py itarare.sp novasenha 3523206
"""

import sys
import os

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import psycopg2
from werkzeug.security import generate_password_hash

CIDADES = {
    "3523206": "Itararé / SP",
    "3145059": "Nova Porteirinha / MG",
    "5107602": "Rondonópolis / MT",
    "5102702": "Canarana / MT",
    "5107065": "Querência / MT",
    "5100201": "Água Boa / MT",
    "2305605": "Independência / CE",
    "3510500": "Caraguatatuba / SP",
}

SQL_CRIAR_TABELA = """
CREATE TABLE IF NOT EXISTS usuarios (
    id            SERIAL PRIMARY KEY,
    username      VARCHAR(100) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    codigo_ibge   VARCHAR(10),
    is_admin      BOOLEAN NOT NULL DEFAULT FALSE,
    ativo         BOOLEAN NOT NULL DEFAULT TRUE,
    criado_em     TIMESTAMP NOT NULL DEFAULT NOW(),
    atualizado_em TIMESTAMP NOT NULL DEFAULT NOW()
);
"""

SQL_UPSERT = """
INSERT INTO usuarios (username, password_hash, codigo_ibge, is_admin)
VALUES (%s, %s, %s, %s)
ON CONFLICT (username) DO UPDATE
    SET password_hash   = EXCLUDED.password_hash,
        codigo_ibge     = EXCLUDED.codigo_ibge,
        is_admin        = EXCLUDED.is_admin,
        atualizado_em   = NOW();
"""


def main():
    args = sys.argv[1:]
    if len(args) < 2:
        print(__doc__)
        sys.exit(1)

    username = args[0]
    senha = args[1]
    is_admin = "--admin" in args
    codigo_ibge = None

    for a in args[2:]:
        if not a.startswith("--"):
            codigo_ibge = a

    if not is_admin and not codigo_ibge:
        print("ERRO: informe um código IBGE ou --admin.")
        sys.exit(1)

    if codigo_ibge and codigo_ibge not in CIDADES:
        print(f"AVISO: código IBGE '{codigo_ibge}' não está na lista de cidades cadastradas.")
        resp = input("Continuar mesmo assim? [s/N] ").strip().lower()
        if resp != "s":
            sys.exit(0)

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("ERRO: variável DATABASE_URL não definida.")
        sys.exit(1)

    hash_senha = generate_password_hash(senha)

    conn = psycopg2.connect(database_url)
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(SQL_CRIAR_TABELA)
                cur.execute(SQL_UPSERT, (username, hash_senha, codigo_ibge, is_admin))

        cidade_label = CIDADES.get(codigo_ibge, codigo_ibge) if codigo_ibge else "(todas)"
        tipo = "ADMIN" if is_admin else "Prefeitura"
        print(f"OK — usuário '{username}' salvo | Tipo: {tipo} | Município: {cidade_label}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
