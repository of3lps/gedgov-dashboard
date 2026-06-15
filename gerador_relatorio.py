import psycopg2
from google import genai
import pdfkit
import os

def gerar_relatorio_inteligente():
    print("[1] Conectando ao Banco de Dados...")
    
    # 1. Puxando os dados reais do MVP
    try:
        conexao = psycopg2.connect(
            dbname="itarare_gov_db", 
            user="admin",             # <-- Atualizado
            password="admin_senha",   # <-- Atualizado
            host="localhost", 
            port="5433"               # <-- A porta correta do seu Docker!
        )
        cursor = conexao.cursor()
        
        query = """
            SELECT 
                SUM((payload->>'valor')::numeric) AS empenhado,
                SUM((payload->>'valorLiberado')::numeric) AS pago,
                SUM((payload->>'valor')::numeric) - SUM((payload->>'valorLiberado')::numeric) AS saldo
            FROM raw_transferegov;
        """
        cursor.execute(query)
        resultado = cursor.fetchone()
        
        empenhado = resultado[0] / 1000000
        pago = resultado[1] / 1000000
        saldo = resultado[2] / 1000000
        
        conexao.close()
        print(f"[OK] Dados extraídos: Empenhado R$ {empenhado:.2f}M | Pago R$ {pago:.2f}M | Saldo R$ {saldo:.2f}M")
        
    except Exception as e:
        print(f"[Erro] Falha ao ler o banco de dados: {e}")
        return

    # 2. Conectando ao Cérebro (Gemini API - Novo SDK)
    print("\n[2] Acionando a Inteligência Artificial (Gemini)...")
    
    CHAVE_GEMINI = "AQ.Ab8RN6LLrkE6F8ZKlzxVDsi-U-hWV9ei-bDqMro-7Q7YuYqmDA" # <-- COLOQUE SUA CHAVE AQUI
    
    try:
        client = genai.Client(api_key=CHAVE_GEMINI)

        prompt = f"""
        Aja como um Consultor Governamental Sênior. Eu tenho os seguintes dados do município de Nova Porteirinha:
        - Total Empenhado: R$ {empenhado:.2f} Milhões
        - Total Pago: R$ {pago:.2f} Milhões
        - Saldo a Executar: R$ {saldo:.2f} Milhões
        
        Sua tarefa é gerar APENAS o código HTML completo (com CSS inline) para um relatório de uma página, seguindo exatamente este design:
        1. Fundo da página branco.
        2. Um título em azul escuro (#1D4B8F): "Panorama Orçamentário - Nova Porteirinha / MG".
        3. Escreva um parágrafo executivo persuasivo e elegante (2 a 3 linhas) analisando a execução e destacando o saldo como uma "oportunidade ativa".
        4. Crie 3 cartões (cards) horizontais grandes e modernos:
           - Cartão 1 (Fundo Cinza Claro, Texto Azul): Total Empenhado.
           - Cartão 2 (Fundo Amarelo #F2C100, Texto Preto): Total Pago.
           - Cartão 3 (Fundo Azul Escuro #1D4B8F, Texto Branco): Saldo a Executar.
        Não use Markdown (como ```html), retorne estritamente o código puro começando com <!DOCTYPE html>.
        """

        resposta_ia = client.models.generate_content(
            model='gemini-3.5-flash',  # Nome exato documentado na versão atual da API
            contents=prompt
        )
        html_gerado = resposta_ia.text.strip()

        if html_gerado.startswith("```html"):
            html_gerado = html_gerado[7:-3]
        elif html_gerado.startswith("```"):
            html_gerado = html_gerado[3:-3]

        print("[OK] Layout e Análise gerados pela IA com sucesso!")
        
    except Exception as e:
        print(f"[Erro] Falha na comunicação com a API da IA: {e}")
        return

    # 3. Impressão do Relatório
    print("\n[3] Gerando os arquivos finais...")
    
    caminho_html = "Relatorio_Nova_Porteirinha.html"
    with open(caminho_html, "w", encoding="utf-8") as f:
        f.write(html_gerado)
    print(f"[OK] Arquivo salvo: {caminho_html} (Abra isso no navegador!)")

    caminho_pdf = "Relatorio_Nova_Porteirinha.pdf"
    try:
        pdfkit.from_file(caminho_html, caminho_pdf)
        print(f"[OK] Arquivo PDF gerado com sucesso: {caminho_pdf}")
    except Exception as e:
        print(f"[Aviso] O HTML foi gerado perfeitamente! Para o PDF, instale o 'wkhtmltopdf' no Windows.")

    print("\n--- Pipeline Finalizado! ---")

if __name__ == "__main__":
    gerar_relatorio_inteligente()