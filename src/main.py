import os
import psycopg2
from psycopg2.extras import Json
from ingestao_transferegov import ingerir_dados_transferegov
from ingestao_siconfi import ingerir_dados_siconfi

# Pega as credenciais pelas variáveis de ambiente configuradas no Docker
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_USER = os.getenv("DB_USER", "admin")
DB_PASSWORD = os.getenv("DB_PASSWORD", "admin_senha")
DB_NAME = os.getenv("DB_NAME", "itarare_gov_db")

def conectar_banco():
    return psycopg2.connect(
        host=DB_HOST,
        user=DB_USER,
        password=DB_PASSWORD,
        dbname=DB_NAME
    )

def criar_tabelas():
    """Cria a estrutura inicial (Camada Raw) usando JSONB."""
    conn = conectar_banco()
    cursor = conn.cursor()
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS raw_transferegov (
            id SERIAL PRIMARY KEY,
            cnpj VARCHAR(20),
            payload JSONB,
            ingested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS raw_siconfi_entregas (
            id SERIAL PRIMARY KEY,
            cod_ibge VARCHAR(20),
            ano INT,
            payload JSONB,
            ingested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    
    conn.commit()
    cursor.close()
    conn.close()
    print("[Banco de Dados] Tabelas verificadas/criadas com sucesso.")

def main():
    print("Iniciando orquestração de dados para o MVP (Itararé-SP)...")
    criar_tabelas()
    
    # 1. Ingestão Transferegov
    print("\n--- Coletando Transferegov ---")
    dados_convenios = ingerir_dados_transferegov()
    if dados_convenios:
        conn = conectar_banco()
        cursor = conn.cursor()
        for item in dados_convenios:
            cursor.execute(
                "INSERT INTO raw_transferegov (cnpj, payload) VALUES (%s, %s)",
                ("46634390000152", Json(item))
            )
        conn.commit()
        cursor.close()
        conn.close()
        print(f"[Sucesso] {len(dados_convenios)} registros do Transferegov salvos no banco.")

    # 2. Ingestão Siconfi (Usaremos 2025 como ano de referência recente)
    print("\n--- Coletando Siconfi ---")
    ano_ref = 2025
    dados_siconfi = ingerir_dados_siconfi(ano_ref)
    if dados_siconfi:
        conn = conectar_banco()
        cursor = conn.cursor()
        for item in dados_siconfi:
            cursor.execute(
                "INSERT INTO raw_siconfi_entregas (cod_ibge, ano, payload) VALUES (%s, %s, %s)",
                ("3523206", ano_ref, Json(item))
            )
        conn.commit()
        cursor.close()
        conn.close()
        print(f"[Sucesso] {len(dados_siconfi)} registros do Siconfi salvos no banco.")

    print("\nPipeline finalizado com sucesso!")

if __name__ == "__main__":
    main()