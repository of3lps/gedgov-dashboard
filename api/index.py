from flask import Flask, render_template, request
import psycopg2
import pandas as pd

app = Flask(__name__, template_folder='templates')

CIDADES = {
    "3523206": "Itararé / SP",
    "3145059": "Nova Porteirinha / MG",
    "5107602": "Rondonópolis / MT",
    "5102702": "Canarana / MT",
    "5107065": "Querência / MT",
    "5100201": "Água Boa / MT",
    "2305605": "Independência / CE"
}

def formatar_real(valor):
    if pd.isna(valor) or valor is None: return "R$ 0,00"
    return f"R$ {float(valor):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

def carregar_dados(codigo_ibge):
    try:
        # Conexão blindada Neon original
        conexao = psycopg2.connect(
            host="ep-damp-math-ateks048-pooler.c-9.us-east-1.aws.neon.tech",
            database="neondb",
            user="neondb_owner",
            password="npg_yRDK80XVWmdg",
            port="5432",
            sslmode="require",
            options="endpoint=ep-damp-math-ateks048-pooler"
        )
        
        # 1. TOTAIS (Sua query exata)
        query_totais = f"""
            SELECT 
                COUNT(*) AS total_convenios,
                SUM((payload->>'valor')::numeric) AS empenhado,
                SUM((payload->>'valorLiberado')::numeric) AS pago,
                SUM(
                    CASE 
                        WHEN payload->>'dataFinalVigencia' IS NOT NULL 
                         AND TO_DATE(payload->>'dataFinalVigencia', 'YYYY-MM-DD') >= CURRENT_DATE 
                        THEN GREATEST((payload->>'valor')::numeric - (payload->>'valorLiberado')::numeric, 0)
                        ELSE 0 
                    END
                ) AS risco,
                SUM(
                    CASE 
                        WHEN payload->>'dataFinalVigencia' IS NOT NULL 
                         AND TO_DATE(payload->>'dataFinalVigencia', 'YYYY-MM-DD') < CURRENT_DATE 
                        THEN GREATEST((payload->>'valor')::numeric - (payload->>'valorLiberado')::numeric, 0)
                        ELSE 0 
                    END
                ) AS perdido
            FROM raw_transferegov
            WHERE codigo_ibge = '{codigo_ibge}';
        """
        df_totais = pd.read_sql(query_totais, conexao)
        
        # 2. DETALHES (Sua query exata)
        query_detalhes = f"""
            SELECT 
                payload->'dimConvenio'->>'numero' AS "Nº Convênio",
                payload->'dimConvenio'->>'objeto' AS "Descrição da Obra",
                payload->'convenente'->>'nome' AS "Entidade Beneficiada",
                (payload->>'valor')::numeric AS "Valor Total",
                (payload->>'valorLiberado')::numeric AS "Valor Pago",
                GREATEST(((payload->>'valor')::numeric - (payload->>'valorLiberado')::numeric), 0) AS "Saldo Restante",
                payload->>'dataFinalVigencia' AS "Vencimento",
                CASE 
                    WHEN payload->>'dataFinalVigencia' IS NULL THEN '⚪ Indefinido'
                    WHEN TO_DATE(payload->>'dataFinalVigencia', 'YYYY-MM-DD') >= CURRENT_DATE THEN '🟢 Ativo'
                    ELSE '🔴 Vencido (Perdido)'
                END AS "Status Vigência"
            FROM raw_transferegov
            WHERE codigo_ibge = '{codigo_ibge}'
            ORDER BY "Status Vigência" DESC, "Saldo Restante" DESC;
        """
        df_detalhes = pd.read_sql(query_detalhes, conexao)
        conexao.close()
        
        # Formatando os dados para a Web
        totais = df_totais.iloc[0]
        dados_totais = {
            'obras': int(totais['total_convenios']) if pd.notna(totais['total_convenios']) else 0,
            'alocado': formatar_real(totais['empenhado']),
            'pago': formatar_real(totais['pago']),
            'risco': formatar_real(totais['risco']),
            'perdido': formatar_real(totais['perdido'])
        }
        
        # Formatando as moedas na tabela de detalhes
        df_detalhes['Valor Total'] = df_detalhes['Valor Total'].apply(formatar_real)
        df_detalhes['Valor Pago'] = df_detalhes['Valor Pago'].apply(formatar_real)
        df_detalhes['Saldo Restante'] = df_detalhes['Saldo Restante'].apply(formatar_real)
        lista_detalhes = df_detalhes.to_dict('records')
        
        return dados_totais, lista_detalhes

    except Exception as e:
        print("Erro:", e)
        return None, None

@app.route('/')
def dashboard():
    # Pega o IBGE da URL, se não existir usa Itararé como padrão
    codigo_ibge = request.args.get('ibge', '3523206')
    nome_cidade = CIDADES.get(codigo_ibge, "Cidade Desconhecida")
    
    totais, detalhes = carregar_dados(codigo_ibge)
    
    return render_template('index.html', 
                           cidades=CIDADES, 
                           ibge_atual=codigo_ibge, 
                           nome_cidade=nome_cidade, 
                           totais=totais, 
                           detalhes=detalhes)

# Variável de entrada para o motor da Vercel
app_handler = app