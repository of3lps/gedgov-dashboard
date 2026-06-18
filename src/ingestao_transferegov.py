import requests
import time
import psycopg2
import json

def ingerir_dados_transferegov():
    # 1. A Carteira de Clientes do seu SaaS
    cidades_alvo = {
        "3523206": "Itararé / SP",
        "3145059": "Nova Porteirinha / MG",
        "5107602": "Rondonópolis / MT",
        "5102702": "Canarana / MT",
        "5107065": "Querência / MT",
        "5100201": "Água Boa / MT",
        "2305605": "Independência / CE",
        "3510500": "Caraguatatuba / SP" # <--- NOVO CLIENTE AQUI TAMBÉM
    }
    
    url_base = "https://api.portaldatransparencia.gov.br/api-de-dados/convenios"
    chave_api_cgu = "b36cb1307e25e24168cae0fff43de646" 
    
    headers = {
        "accept": "application/json",
        "chave-api-dados": chave_api_cgu
    }

    print(f"[Engine] Iniciando a esteira de carga Pura para {len(cidades_alvo)} clientes...")

    try:
        # Conexão blindada Neon
        conexao = psycopg2.connect(
            host="ep-damp-math-ateks048-pooler.c-9.us-east-1.aws.neon.tech",
            database="neondb",
            user="neondb_owner",
            password="npg_yRDK80XVWmdg",
            port="5432",
            sslmode="require",
            options="endpoint=ep-damp-math-ateks048-pooler"
        )
        cursor = conexao.cursor()
    except Exception as e:
        print(f"[Erro] Falha ao conectar ao banco: {e}")
        return

    for codigo_ibge, nome_cidade in cidades_alvo.items():
        print(f"\n==================================================")
        print(f"-> PROCESSANDO: {nome_cidade} (IBGE: {codigo_ibge})")
        print(f"==================================================")
        
        todos_convenios_da_cidade = []
        pagina_atual = 1

        while True:
            params = {"codigoIBGE": codigo_ibge, "pagina": pagina_atual}
            
            try:
                response = requests.get(url_base, headers=headers, params=params, timeout=15)
                response.raise_for_status()
                dados_pagina = response.json()
                
                if not dados_pagina:
                    break
                    
                todos_convenios_da_cidade.extend(dados_pagina)
                print(f"   [API] Página {pagina_atual}: +{len(dados_pagina)} registros.")
                pagina_atual += 1
                time.sleep(1) 
                
            except Exception as e:
                print(f"   [API] Erro: {e}")
                break

        print(f"   [Sucesso] {len(todos_convenios_da_cidade)} convênios baixados.")

        if todos_convenios_da_cidade:
            
            # --- IDEMPOTÊNCIA (Sem Vacina) ---
            cursor.execute("DELETE FROM raw_transferegov WHERE codigo_ibge = %s;", (codigo_ibge,))
            
            registros_inseridos = 0
            for convenio in todos_convenios_da_cidade:
                payload_json = json.dumps(convenio)
                
                query_insert = """
                    INSERT INTO raw_transferegov (payload, codigo_ibge) 
                    VALUES (%s, %s);
                """
                cursor.execute(query_insert, (payload_json, codigo_ibge))
                registros_inseridos += 1
                
            conexao.commit()
            print(f"   [Banco] {registros_inseridos} registros carregados (Espelho Fiel).")

    cursor.close()
    conexao.close()
    print("\n--- [FIM DA ESTEIRA] Processo finalizado com sucesso! ---")

if __name__ == "__main__":
    ingerir_dados_transferegov()