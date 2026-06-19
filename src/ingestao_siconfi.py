import json

import requests

from config import CIDADES, get_conn


def _buscar_entregas(codigo_ibge, ano_referencia):
    """Consome o Data Lake do Siconfi (Tesouro Nacional) para um município/ano.

    Retorna os itens BRUTOS da API (espelho fiel), preservando todas as chaves
    originais — entre elas: entregavel, status_relatorio, instituicao, periodo,
    periodicidade, data_status, forma_envio, tipo_relatorio.
    """
    url_base = "https://apidatalake.tesouro.gov.br/ords/siconfi/tt/extrato_entregas"
    params = {"id_ente": codigo_ibge, "an_referencia": ano_referencia}

    try:
        response = requests.get(url_base, params=params, timeout=15)
        response.raise_for_status()

        # O Siconfi retorna os dados dentro da chave 'items'
        return response.json().get("items", [])

    except requests.exceptions.RequestException as e:
        print(f"   [Siconfi] Erro na ingestão ({codigo_ibge}/{ano_referencia}): {e}")
        return []


def ingerir_dados_siconfi(ano_referencia):
    """Ingere as entregas fiscais do Siconfi para TODAS as cidades da carteira.

    Persiste direto no banco com idempotência por cidade+ano (mesmo padrão do
    Transferegov: DELETE seguido de INSERT).
    """
    print(f"[Siconfi] Iniciando ingestão para {len(CIDADES)} clientes (Ano: {ano_referencia})...")

    try:
        conexao = get_conn()
        cursor = conexao.cursor()
    except Exception as e:
        print(f"[Erro] Falha ao conectar ao banco: {e}")
        return

    for codigo_ibge, nome_cidade in CIDADES.items():
        entregas = _buscar_entregas(codigo_ibge, ano_referencia)
        print(f"   -> {nome_cidade} (IBGE: {codigo_ibge}): {len(entregas)} entregas.")

        # --- IDEMPOTÊNCIA (Espelho Fiel) por cidade + ano ---
        cursor.execute(
            "DELETE FROM raw_siconfi_entregas WHERE cod_ibge = %s AND ano = %s;",
            (codigo_ibge, ano_referencia)
        )

        for entrega in entregas:
            cursor.execute(
                "INSERT INTO raw_siconfi_entregas (cod_ibge, ano, payload) VALUES (%s, %s, %s);",
                (codigo_ibge, ano_referencia, json.dumps(entrega))
            )

        conexao.commit()

    cursor.close()
    conexao.close()
    print("[Siconfi] Ingestão finalizada com sucesso!")


# Execução isolada para teste
if __name__ == "__main__":
    ingerir_dados_siconfi(ano_referencia=2024)
