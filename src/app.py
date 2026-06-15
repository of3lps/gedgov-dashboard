import streamlit as st
import psycopg2
import pandas as pd

# ==========================================
# CONFIGURAÇÃO VISUAL E LOGO
# ==========================================
st.set_page_config(
    page_title="Gedgov - BI Executivo",
    page_icon="📊",
    layout="wide"
)

st.markdown("""
    <style>
    /* 1. Remove completamente a barra superior cinzenta do GitHub e do Streamlit */
    header {
        visibility: hidden !important;
        display: none !important;
        height: 0px !important;
    }
    
    /* 2. Remove o menu flutuante dos 3 pontinhos */
    #MainMenu {
        visibility: hidden !important;
    }
    
    /* 3. Remove o rodapé 'Made with Streamlit' */
    footer {
        visibility: hidden !important;
    }
    
    /* 4. Remove botões residuais de Deploy que possam aparecer */
    .stAppDeployButton {
        display: none !important;
    }
    
    /* Seus estilos visuais corporativos */
    .main-title { color: #1D4B8F; font-size: 34px; font-weight: bold; margin-bottom: 5px; }
    .sub-title { color: #666; font-size: 16px; margin-bottom: 25px; }
    </style>
""", unsafe_allow_html=True)

CIDADES = {
    "3523206": "Itararé / SP",
    "3145059": "Nova Porteirinha / MG",
    "5107602": "Rondonópolis / MT",
    "5102702": "Canarana / MT",
    "5107065": "Querência / MT",
    "5100201": "Água Boa / MT",
    "2305605": "Independência / CE"
}

# ==========================================
# MOTOR BLINDADO (CACHE DE MEMÓRIA)
# ==========================================
@st.cache_data(ttl=600)  
def carregar_dados_SaaS(codigo_ibge):
    try:
        conexao = psycopg2.connect(
            host="ep-damp-math-ateks048-pooler.c-9.us-east-1.aws.neon.tech",
            database="neondb",
            user="neondb_owner",
            password="npg_yRDK80XVWmdg",
            port="5432",
            sslmode="require",
            options="endpoint=ep-damp-math-ateks048-pooler"
        )
        
        # 1. TOTAIS (Usando GREATEST para evitar que saldos negativos reduzam a soma)
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
        
        # 2. DETALHES (Usando GREATEST na coluna de Saldo Restante)
        query_detalhes = f"""
            SELECT 
                payload->'dimConvenio'->>'numero' AS "Nº Convênio",
                payload->'dimConvenio'->>'objeto' AS "Descrição da Obra",
                payload->'convenente'->>'nome' AS "Entidade Beneficiada",
                (payload->>'valor')::numeric AS "Valor Total (R$)",
                (payload->>'valorLiberado')::numeric AS "Valor Pago (R$)",
                GREATEST(((payload->>'valor')::numeric - (payload->>'valorLiberado')::numeric), 0) AS "Saldo Restante (R$)",
                payload->>'dataFinalVigencia' AS "Vencimento",
                CASE 
                    WHEN payload->>'dataFinalVigencia' IS NULL THEN '⚪ Indefinido'
                    WHEN TO_DATE(payload->>'dataFinalVigencia', 'YYYY-MM-DD') >= CURRENT_DATE THEN '🟢 Ativo'
                    ELSE '🔴 Vencido (Perdido)'
                END AS "Status Vigência"
            FROM raw_transferegov
            WHERE codigo_ibge = '{codigo_ibge}'
            ORDER BY "Status Vigência" DESC, "Saldo Restante (R$)" DESC;
        """
        df_detalhes = pd.read_sql(query_detalhes, conexao)
        
        conexao.close()
        return df_totais.iloc[0], df_detalhes
        
    except Exception as e:
        st.error(f"Erro na conexão com o banco de dados: {e}")
        return None, None

# ==========================================
# INTERFACE DO USUÁRIO (UI)
# ==========================================
try:
    st.sidebar.image("src/logo.png", use_container_width=True)
except FileNotFoundError:
    st.sidebar.markdown("### GEDGOV") 

st.sidebar.markdown("<br>", unsafe_allow_html=True) 

opcao_ibge = st.sidebar.selectbox(
    "Município Ativo:", 
    options=list(CIDADES.keys()),
    format_func=lambda x: CIDADES[x]
)

nome_cidade = CIDADES[opcao_ibge]

st.markdown("<div class='main-title'>📊 Portal de Gestão Orçamentária Executiva</div>", unsafe_allow_html=True)
st.markdown(f"<div class='sub-title'>Visualização ativa para o cliente: <b>{nome_cidade}</b></div>", unsafe_allow_html=True)

totais, detalhes = carregar_dados_SaaS(opcao_ibge)

if totais is not None and not detalhes.empty and pd.notna(totais['total_convenios']) and totais['total_convenios'] > 0:
    
    def formatar_real(valor):
        if pd.isna(valor) or valor is None: return "R$ 0,00"
        return f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

    col1, col2, col3, col4, col5 = st.columns(5)
    
    with col1:
        st.metric(label="Total de Obras", value=int(totais['total_convenios']))
    with col2:
        st.metric(label="Valor Alocado", value=formatar_real(totais['empenhado']))
    with col3:
        st.metric(label="Valor Pago", value=formatar_real(totais['pago']))
    with col4:
        st.metric(label="⚠️ Saldo em Risco (Ativo)", value=formatar_real(totais['risco']))
    with col5:
        st.metric(label="❌ Dinheiro Perdido", value=formatar_real(totais['perdido']))

    st.markdown("---")
    st.markdown("### 📋 Portfólio de Convênios e Projetos")
    
    st.dataframe(
        detalhes,
        use_container_width=True,
        hide_index=True
    )
    
else:
    st.warning(f"Aguardando dados para {nome_cidade}. Certifique-se de ter rodado a ingestão para este banco na nuvem!")