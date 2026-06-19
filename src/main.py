from config import get_conn
from ingestao_transferegov import ingerir_dados_transferegov
from ingestao_siconfi import ingerir_dados_siconfi
from ingestao_convenios_sp import ingerir_convenios_sp


def criar_tabelas():
    """Cria a estrutura da Camada Raw (JSONB) com o esquema usado pela ingestão."""
    conn = get_conn()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS raw_transferegov (
            id SERIAL PRIMARY KEY,
            codigo_ibge VARCHAR(20),
            payload JSONB,
            ingested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_transferegov_ibge ON raw_transferegov (codigo_ibge);"
    )

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS raw_siconfi_entregas (
            id SERIAL PRIMARY KEY,
            cod_ibge VARCHAR(20),
            ano INT,
            payload JSONB,
            ingested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_siconfi_ibge ON raw_siconfi_entregas (cod_ibge);"
    )

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS raw_convenios_sp (
            id SERIAL PRIMARY KEY,
            codigo_ibge VARCHAR(20),
            payload JSONB,
            ingested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_convenios_sp_ibge ON raw_convenios_sp (codigo_ibge);"
    )

    conn.commit()
    cursor.close()
    conn.close()
    print("[Banco de Dados] Tabelas verificadas/criadas com sucesso.")


def main():
    print("Iniciando orquestração de dados do MVP...")
    criar_tabelas()

    # 1. Ingestão Transferegov (a função persiste no banco por conta própria)
    print("\n--- Coletando Transferegov ---")
    ingerir_dados_transferegov()

    # 2. Ingestão Siconfi (também persiste por conta própria, para todas as cidades)
    print("\n--- Coletando Siconfi ---")
    ano_ref = 2025
    ingerir_dados_siconfi(ano_ref)

    # 3. Ingestão de convênios estaduais de SP (CSV em lote, só cidades de SP)
    print("\n--- Coletando Convênios Estaduais (SP) ---")
    ingerir_convenios_sp()

    print("\nPipeline finalizado com sucesso!")


if __name__ == "__main__":
    main()
