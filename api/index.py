import os

from flask import Flask, render_template, request
import psycopg2
import psycopg2.extras

app = Flask(__name__, template_folder='templates')

# A Carteira de Clientes do seu SaaS
# (mantida aqui porque a Vercel empacota apenas a pasta api/ — não importar de src/)
CIDADES = {
    "3523206": "Itararé / SP",
    "3145059": "Nova Porteirinha / MG",
    "5107602": "Rondonópolis / MT",
    "5102702": "Canarana / MT",
    "5107065": "Querência / MT",
    "5100201": "Água Boa / MT",
    "2305605": "Independência / CE",
    "3510500": "Caraguatatuba / SP"
}

IBGE_PADRAO = "3523206"


def formatar_real(valor):
    if valor is None: return "R$ 0,00"
    return f"R$ {float(valor):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def conectar():
    """Abre conexão lendo a connection string da env var DATABASE_URL."""
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL não configurada no ambiente.")
    return psycopg2.connect(database_url)


def carregar_dados(codigo_ibge):
    conexao = None
    try:
        conexao = conectar()

        # Cursor que retorna dicionários em vez de tuplas
        cursor = conexao.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # 1. TOTAIS (query parametrizada — sem interpolação de input do usuário)
        query_totais = """
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
            WHERE codigo_ibge = %s;
        """
        cursor.execute(query_totais, (codigo_ibge,))
        totais = cursor.fetchone()

        # 2. DETALHES (query parametrizada)
        query_detalhes = """
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
            WHERE codigo_ibge = %s
            ORDER BY "Status Vigência" DESC, "Saldo Restante" DESC;
        """
        cursor.execute(query_detalhes, (codigo_ibge,))
        detalhes_brutos = cursor.fetchall()

        # 3. CONFORMIDADE FISCAL (Siconfi) — entregas do ano mais recente disponível
        query_siconfi = """
            SELECT
                payload->>'documento' AS "Documento",
                payload->>'periodo' AS "Período",
                payload->>'status' AS "Status",
                payload->>'data_status' AS "Data Status"
            FROM raw_siconfi_entregas
            WHERE cod_ibge = %s
              AND ano = (SELECT MAX(ano) FROM raw_siconfi_entregas WHERE cod_ibge = %s)
            ORDER BY payload->>'periodo', payload->>'documento';
        """
        cursor.execute(query_siconfi, (codigo_ibge, codigo_ibge))
        siconfi_brutos = cursor.fetchall()

        cursor.close()

        # Formatando os totais
        dados_totais = {
            'obras': totais['total_convenios'] if totais['total_convenios'] else 0,
            'alocado': formatar_real(totais['empenhado']),
            'pago': formatar_real(totais['pago']),
            'risco': formatar_real(totais['risco']),
            'perdido': formatar_real(totais['perdido'])
        }

        # Formatando as moedas na tabela de detalhes
        lista_detalhes = []
        for linha in detalhes_brutos:
            lista_detalhes.append({
                'Nº Convênio': linha['Nº Convênio'],
                'Descrição da Obra': linha['Descrição da Obra'],
                'Entidade Beneficiada': linha['Entidade Beneficiada'],
                'Valor Total': formatar_real(linha['Valor Total']),
                'Valor Pago': formatar_real(linha['Valor Pago']),
                'Saldo Restante': formatar_real(linha['Saldo Restante']),
                'Vencimento': linha['Vencimento'],
                'Status Vigência': linha['Status Vigência']
            })

        lista_siconfi = [dict(linha) for linha in siconfi_brutos]

        return dados_totais, lista_detalhes, lista_siconfi

    except Exception as e:
        print("Erro:", e)
        return None, None, None
    finally:
        if conexao is not None:
            conexao.close()


@app.route('/')
def dashboard():
    codigo_ibge = request.args.get('ibge', IBGE_PADRAO)
    # Validação: só aceitamos códigos da carteira de clientes (evita SQL injection
    # e acesso a dados arbitrários). Qualquer valor desconhecido cai no padrão.
    if codigo_ibge not in CIDADES:
        codigo_ibge = IBGE_PADRAO
    nome_cidade = CIDADES.get(codigo_ibge, "Cidade Desconhecida")

    totais, detalhes, siconfi = carregar_dados(codigo_ibge)

    return render_template('index.html',
                           cidades=CIDADES,
                           ibge_atual=codigo_ibge,
                           nome_cidade=nome_cidade,
                           totais=totais,
                           detalhes=detalhes,
                           siconfi=siconfi)


# Variável de entrada para a Vercel
app_handler = app
