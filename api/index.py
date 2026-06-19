import os

from flask import Flask, render_template, request
import psycopg2
import psycopg2.extras

try:
    # Carrega o .env automaticamente em ambiente local (procura na raiz do projeto).
    # Em produção (Vercel) as env vars vêm do painel e o dotenv é simplesmente ignorado.
    from dotenv import load_dotenv

    load_dotenv()
    load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
except ImportError:
    pass

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


def _num(valor):
    """Converte valor numérico do banco em float (0.0 se None)."""
    return float(valor) if valor is not None else 0.0


# Mapeia o código de status do Siconfi para (rótulo legível, cor do badge Bootstrap).
SICONFI_STATUS = {
    "HO": ("Homologado", "success"),
    "RE": ("Recebido", "info"),
}


def status_siconfi(codigo, data_status):
    """Resolve o badge de status de uma entrega fiscal."""
    if codigo in SICONFI_STATUS:
        return SICONFI_STATUS[codigo]
    if codigo:  # código desconhecido — mostra como veio
        return (codigo, "secondary")
    if data_status:  # sem status formal, mas foi enviado (ex.: MSC)
        return ("Entregue", "secondary")
    return ("Pendente", "warning")


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
                payload->>'entregavel' AS documento,
                payload->>'instituicao' AS instituicao,
                payload->>'periodo' AS periodo,
                payload->>'periodicidade' AS periodicidade,
                payload->>'status_relatorio' AS status,
                payload->>'data_status' AS data_status
            FROM raw_siconfi_entregas
            WHERE cod_ibge = %s
              AND ano = (SELECT MAX(ano) FROM raw_siconfi_entregas WHERE cod_ibge = %s)
            ORDER BY payload->>'instituicao', payload->>'entregavel', payload->>'periodo';
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

        # Formatando as moedas na tabela de detalhes + contagem por status (gráficos)
        lista_detalhes = []
        ativos = vencidos = indefinidos = 0
        for linha in detalhes_brutos:
            status_vig = linha['Status Vigência']
            if 'Ativo' in status_vig:
                ativos += 1
            elif 'Vencido' in status_vig:
                vencidos += 1
            else:
                indefinidos += 1
            lista_detalhes.append({
                'Nº Convênio': linha['Nº Convênio'],
                'Descrição da Obra': linha['Descrição da Obra'],
                'Entidade Beneficiada': linha['Entidade Beneficiada'],
                'Valor Total': formatar_real(linha['Valor Total']),
                'Valor Pago': formatar_real(linha['Valor Pago']),
                'Saldo Restante': formatar_real(linha['Saldo Restante']),
                'Vencimento': linha['Vencimento'],
                'Status Vigência': status_vig
            })

        # Entregas Siconfi com badge de status resolvido
        lista_siconfi = []
        for linha in siconfi_brutos:
            rotulo, cor = status_siconfi(linha['status'], linha['data_status'])
            lista_siconfi.append({
                'documento': linha['documento'],
                'instituicao': linha['instituicao'],
                'periodo': linha['periodo'],
                'periodicidade': linha['periodicidade'],
                'status_rotulo': rotulo,
                'status_cor': cor,
                'data_status': linha['data_status'],
            })

        # Dados numéricos para os gráficos (Chart.js)
        grafico = {
            'pago': _num(totais['pago']),
            'risco': _num(totais['risco']),
            'perdido': _num(totais['perdido']),
            'ativos': ativos,
            'vencidos': vencidos,
            'indefinidos': indefinidos,
        }

        return dados_totais, lista_detalhes, lista_siconfi, grafico

    except Exception as e:
        print("Erro:", e)
        return None, None, None, None
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

    totais, detalhes, siconfi, grafico = carregar_dados(codigo_ibge)

    return render_template('index.html',
                           cidades=CIDADES,
                           ibge_atual=codigo_ibge,
                           nome_cidade=nome_cidade,
                           totais=totais,
                           detalhes=detalhes,
                           siconfi=siconfi,
                           grafico=grafico)


# Variável de entrada para a Vercel
app_handler = app


if __name__ == '__main__':
    # Execução local: python api/index.py  ->  http://127.0.0.1:5000
    app.run(host='127.0.0.1', port=5000, debug=True)
