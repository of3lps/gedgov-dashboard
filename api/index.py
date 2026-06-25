import os
import functools

from flask import Flask, render_template, request, session, redirect, url_for, flash
from werkzeug.security import check_password_hash
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
app.secret_key = os.environ.get("SECRET_KEY", "dev-insecure-key-troque-em-producao")

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
    "2301109": "Aracati / CE",
    "3159605": "Santa Rita do Sapucaí / MG",
    "3510500": "Caraguatatuba / SP"
}

IBGE_PADRAO = "3523206"


def login_required(f):
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("user_id"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


def formatar_real(valor):
    if valor is None: return "R$ 0,00"
    return f"R$ {float(valor):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _num(valor):
    """Converte valor numérico do banco em float (0.0 se None)."""
    return float(valor) if valor is not None else 0.0


def _brl_to_float(texto):
    """Converte um valor monetário BR ('R$ 480.000,00') em float (0.0 se vazio)."""
    if not texto:
        return 0.0
    limpo = str(texto).replace("R$", "").replace("\xa0", "").strip()
    limpo = limpo.replace(".", "").replace(",", ".")
    try:
        return float(limpo)
    except ValueError:
        return 0.0


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
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL não configurada no ambiente.")
    return psycopg2.connect(database_url)


def buscar_usuario(username):
    conexao = None
    try:
        conexao = conectar()
        cursor = conexao.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cursor.execute(
            "SELECT id, username, password_hash, codigo_ibge, is_admin FROM usuarios WHERE username = %s AND ativo = TRUE;",
            (username,)
        )
        return cursor.fetchone()
    except Exception as e:
        print("Erro buscar_usuario:", e)
        return None
    finally:
        if conexao:
            conexao.close()


def carregar_dados(codigo_ibge):
    conexao = None
    try:
        conexao = conectar()

        # Cursor que retorna dicionários em vez de tuplas
        cursor = conexao.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # 1. CONVÊNIOS (dados numéricos crus — filtro/ordenação/KPIs ficam no cliente)
        query_convenios = """
            SELECT
                payload->>'id' AS id,
                payload->'dimConvenio'->>'numero' AS numero,
                payload->'dimConvenio'->>'codigo' AS codigo,
                payload->'dimConvenio'->>'objeto' AS objeto,
                payload->>'situacao' AS situacao,
                payload->'tipoInstrumento'->>'descricao' AS tipo_instrumento,
                payload->>'numeroProcesso' AS processo,
                payload->'convenente'->>'nome' AS entidade,
                payload->'convenente'->>'cnpjFormatado' AS entidade_cnpj,
                payload->'convenente'->>'tipo' AS entidade_tipo,
                payload->'orgao'->'orgaoMaximo'->>'nome' AS ministerio,
                payload->'unidadeGestora'->>'nome' AS unidade_gestora,
                (payload->>'valor')::numeric AS valor,
                (payload->>'valorLiberado')::numeric AS pago,
                (payload->>'valorContrapartida')::numeric AS contrapartida,
                (payload->>'valorDaUltimaLiberacao')::numeric AS ult_lib_valor,
                payload->>'dataUltimaLiberacao' AS ult_lib_data,
                GREATEST(((payload->>'valor')::numeric - (payload->>'valorLiberado')::numeric), 0) AS saldo,
                payload->>'dataInicioVigencia' AS inicio,
                payload->>'dataFinalVigencia' AS venc,
                payload->>'dataPublicacao' AS publicacao,
                payload->>'parlamentar_nome' AS parlamentar_nome,
                payload->>'parlamentar_tipo' AS parlamentar_tipo,
                CASE
                    WHEN payload->>'dataFinalVigencia' IS NULL THEN 'indef'
                    WHEN TO_DATE(payload->>'dataFinalVigencia', 'YYYY-MM-DD') >= CURRENT_DATE THEN 'ativo'
                    ELSE 'vencido'
                END AS status
            FROM raw_transferegov
            WHERE codigo_ibge = %s
            ORDER BY status DESC, saldo DESC;
        """
        cursor.execute(query_convenios, (codigo_ibge,))
        convenios_brutos = cursor.fetchall()

        # 2. CONFORMIDADE FISCAL (Siconfi) — entregas do ano mais recente disponível
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

        # 3. CONVÊNIOS ESTADUAIS (SP) — payload cru do CSV da SGRI; só cidades de SP
        cursor.execute(
            "SELECT payload FROM raw_convenios_sp WHERE codigo_ibge = %s;",
            (codigo_ibge,),
        )
        convenios_sp_brutos = cursor.fetchall()

        # 4. TRANSFERÊNCIAS ESPECIAIS ("pix parlamentar") — repasses diretos sem SICONV
        cursor.execute(
            """
            SELECT payload FROM raw_transferencias_especiais
            WHERE codigo_ibge = %s
              AND (payload->>'valor')::numeric >= 1000
            ORDER BY (payload->>'ano')::int DESC,
                     (payload->>'valor')::numeric DESC;
            """,
            (codigo_ibge,),
        )
        tes_brutos = cursor.fetchall()

        cursor.close()

        # Convênios com valores numéricos (KPIs/gráficos/filtros são calculados no cliente)
        convenios = []
        for linha in convenios_brutos:
            convenios.append({
                'id': linha['id'],
                'n': linha['numero'],
                'codigo': linha['codigo'],
                'obra': linha['objeto'],
                'situacao': linha['situacao'],
                'tipo': linha['tipo_instrumento'],
                'processo': linha['processo'],
                'entidade': linha['entidade'],
                'entidade_cnpj': linha['entidade_cnpj'],
                'entidade_tipo': linha['entidade_tipo'],
                'ministerio': linha['ministerio'],
                'ug': linha['unidade_gestora'],
                'valor': _num(linha['valor']),
                'pago': _num(linha['pago']),
                'contrapartida': _num(linha['contrapartida']),
                'ult_lib_valor': _num(linha['ult_lib_valor']),
                'ult_lib_data': linha['ult_lib_data'],
                'saldo': _num(linha['saldo']),
                'inicio': linha['inicio'],       # 'YYYY-MM-DD' ou None
                'venc': linha['venc'],           # 'YYYY-MM-DD' ou None
                'publicacao': linha['publicacao'],
                'status': linha['status'],       # 'ativo' | 'vencido' | 'indef'
                'parlamentar': linha['parlamentar_nome'],
                'parlamentar_tipo': linha['parlamentar_tipo'],
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

        # Convênios estaduais: payload é o dicionário cru do CSV (chaves em PT com acento).
        # Parseamos valores/status aqui; o filtro/ordenação fica no cliente.
        convenios_sp = []
        for linha in convenios_sp_brutos:
            p = linha['payload']
            numero = (p.get('Convênio') or '').strip()
            assinatura = (p.get('Data de Assinatura') or '').strip()
            convenios_sp.append({
                'demanda': p.get('Demanda'),
                'convenio': numero,
                'obra': p.get('Nome da Obra'),
                'portfolio': p.get('Portfólio'),
                'origem': p.get('Origem'),                       # parlamentar/origem do recurso
                'origem_demanda': p.get('Origem da Demanda'),    # ex.: 'Emenda LOA'
                'valor_estado': _brl_to_float(p.get('Valor do estado')),
                'valor_total': _brl_to_float(p.get('Valor da demanda')),
                'ano': p.get('Ano'),
                'processo': p.get('Processo'),
                'er': p.get('Escritório Regional'),
                'criacao': p.get('Data de criação da demanda'),
                'tramitacao': p.get('Data da última tramitação'),
                'assinatura': assinatura,
                'aditamento': (p.get('Solicitação de Aditamento Pendente') or '').strip(),
                'assinado': bool(numero and assinatura),
            })

        # Transferências Especiais: monta lista limpa para o template
        transferencias_especiais = []
        for linha in tes_brutos:
            p = linha['payload']
            transferencias_especiais.append({
                'parlamentar': p.get('parlamentar', ''),
                'valor': _num(p.get('valor', 0)),
                'ano': p.get('ano', ''),
                'documento': p.get('documento', ''),
                'funcao': p.get('funcao', ''),
                'cod_emenda': p.get('cod_emenda', ''),
            })

        return convenios, lista_siconfi, convenios_sp, transferencias_especiais

    except Exception as e:
        print("Erro:", e)
        return None, None, None, None
    finally:
        if conexao is not None:
            conexao.close()


@app.route('/login', methods=['GET', 'POST'])
def login():
    if session.get("user_id"):
        return redirect(url_for("dashboard"))

    erro = None
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        usuario = buscar_usuario(username)
        if usuario and check_password_hash(usuario['password_hash'], password):
            session.clear()
            session['user_id'] = usuario['id']
            session['username'] = usuario['username']
            session['codigo_ibge'] = usuario['codigo_ibge']
            session['is_admin'] = bool(usuario['is_admin'])
            return redirect(url_for("dashboard"))
        erro = "Usuário ou senha inválidos."

    return render_template('login.html', erro=erro)


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route('/')
@login_required
def dashboard():
    is_admin = session.get('is_admin', False)

    if is_admin:
        # Admin pode trocar de cidade via query param
        codigo_ibge = request.args.get('ibge', IBGE_PADRAO)
        if codigo_ibge not in CIDADES:
            codigo_ibge = IBGE_PADRAO
        cidades_visíveis = CIDADES
    else:
        # Prefeitura: usa apenas o código vinculado à conta
        codigo_ibge = session.get('codigo_ibge') or IBGE_PADRAO
        if codigo_ibge not in CIDADES:
            codigo_ibge = IBGE_PADRAO
        cidades_visíveis = None  # sem seletor

    nome_cidade = CIDADES.get(codigo_ibge, "Cidade Desconhecida")
    convenios, siconfi, convenios_sp, transferencias_especiais = carregar_dados(codigo_ibge)

    return render_template('index.html',
                           is_admin=is_admin,
                           username=session.get('username'),
                           cidades=cidades_visíveis,
                           ibge_atual=codigo_ibge,
                           nome_cidade=nome_cidade,
                           convenios=convenios if convenios is not None else [],
                           total_obras=len(convenios) if convenios else 0,
                           siconfi=siconfi,
                           convenios_sp=convenios_sp if convenios_sp is not None else [],
                           total_sp=len(convenios_sp) if convenios_sp else 0,
                           transferencias_especiais=transferencias_especiais if transferencias_especiais is not None else [],
                           total_te=len(transferencias_especiais) if transferencias_especiais else 0)


# Variável de entrada para a Vercel
app_handler = app


if __name__ == '__main__':
    # Execução local: python api/index.py  ->  http://127.0.0.1:5000
    app.run(host='127.0.0.1', port=5000, debug=True)
