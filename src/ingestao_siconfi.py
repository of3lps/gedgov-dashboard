import requests

def ingerir_dados_siconfi(ano_referencia):
    """
    Consome o Data Lake do Siconfi (Tesouro Nacional).
    Filtra pelo Código IBGE de Itararé-SP para verificar as entregas fiscais.
    """
    ibge_itarare = "3523206"
    url_base = "https://apidatalake.tesouro.gov.br/ords/siconfi/tt/extrato_entregas"
    
    params = {
        "id_ente": ibge_itarare,
        "an_referencia": ano_referencia
    }

    try:
        response = requests.get(url_base, params=params, timeout=15)
        response.raise_for_status()
        
        # O Siconfi retorna os dados dentro da chave 'items'
        dados = response.json().get("items", [])
        
        entregas_processadas = []
        
        for entrega in dados:
            entregas_processadas.append({
                "documento": entrega.get("entrega"), # Ex: RREO, RGF, DCA
                "periodo": entrega.get("periodo"),
                "status": entrega.get("status_entrega"),
                "data_status": entrega.get("data_status")
            })
            
        print(f"[Siconfi] {len(entregas_processadas)} registros de entrega processados para Itararé-SP (Ano: {ano_referencia}).")
        return entregas_processadas

    except requests.exceptions.RequestException as e:
        print(f"Erro na ingestão do Siconfi: {e}")
        return []

# Execução isolada para teste
if __name__ == "__main__":
    # Importante: usar o ano de exercício atual ou anterior para validação
    dados_conformidade = ingerir_dados_siconfi(ano_referencia=2024)