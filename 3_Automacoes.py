import streamlit as st
import pandas as pd
from firebird.driver import connect
from datetime import datetime, timedelta
from io import BytesIO

# ------------------------------
# Configurações da Página
# ------------------------------
st.set_page_config(page_title="Relatórios Financeiros", layout="wide")
st.title("Geração de Relatórios Financeiros")

# --- Mapeamento de Empresas e Contas ---
EMPRESAS = {
    "Plugtech Brasil": [
        'BB PLUG BRASIL RF', 'BNB PLUG BRASIL 8299', 'BNB ES FI PLUG BRASI', 'BB PLUG BRASIL',
        'BNB RS FI PLUG BRASI', 'BNB PLUG BRASIL13815', 'BNB PLUG BRASIL13910', 'CEF PLUG BRASIL',
        'CEF AP PLUG BRASIL', 'ADM PLUG BRASIL', 'PERDA CONT PLUG BRAS', 'PJBANK PLUGTECH BRAS',
        'CARTAO 9412 PLUG BRA', 'F RESERVA P BRASIL'
    ],
    "Plugtech Gestão": [
        'BB PLUG GESTAO RF', 'BB PLUG GESTAO', 'SICRED CAPITAL GESTA', 'ADM PLUG GESTAO',
        'BNB PLUG GESTAO32495', 'PJBANK PLUGTECH GEST', 'SICRED PLUG GESTAO'
    ],
    "Plugtech Serviços": [
        'BB PLUG SERVICOS RF', 'BB PLUG SERVICOS', 'BNB PLUG SERV 26551', 'BNB PLUG SERVIC28454',
        'BNB FI AT PLUG SERVI', 'CEF PLUG SERVICOS', 'CEF AP PLUG SERVICOS', 'TESOURARIA PLUG SERV',
        'ADM PLUG SERVICOS', 'PERDA CONT PLUG SERV', 'CARTAO 3948 PLUG SER', 'PJBANK PLUGTECG SERV',
        'F RESERVA P SERVICOS'
    ]
}

# ------------------------------
# Conexão com o Banco de Dados
# ------------------------------
@st.cache_resource(ttl=600)
def get_connection():
    try:
        conn = connect(
            database=f"{st.secrets.database.host}:{st.secrets.database.path}",
            user=st.secrets.database.user,
            password=st.secrets.database.password,
            charset=st.secrets.database.charset
        )
        return conn
    except Exception as e:
        st.error(f"Erro ao conectar ao banco de dados: {e}")
        return None

@st.cache_data(ttl=300)
def fetch_data(query, params=None):
    conn = get_connection()
    if conn is None:
        return pd.DataFrame()
    try:
        df = pd.read_sql(query, conn, params=params)
        df.columns = df.columns.str.lower()
        return df
    except Exception as e:
        st.error(f"Erro ao executar a query: {e}")
        st.code(query, language="sql")
        return pd.DataFrame()

# ------------------------------
# Função para Download
# ------------------------------
def to_excel(df):
    """Converte um DataFrame para um arquivo Excel em memória para download."""
    output = BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df.to_excel(writer, index=False, sheet_name='Relatorio')
    processed_data = output.getvalue()
    return processed_data

# ------------------------------
# Sidebar e Filtros
# ------------------------------
st.sidebar.header("Filtros Gerais")
empresa_selecionada = st.sidebar.selectbox("Filtrar por Empresa", ["Todas"] + list(EMPRESAS.keys()))
data_inicio = st.sidebar.date_input("Data de Início", datetime.now().date().replace(day=1))
data_fim = st.sidebar.date_input("Data de Fim", (datetime.now().date() + timedelta(days=32)).replace(day=1) - timedelta(days=1))

# --- Construção da cláusula de filtro SQL ---
filtro_str = ""
filtro_params = []
if empresa_selecionada != 'Todas':
    contas = EMPRESAS.get(empresa_selecionada, [])
    if contas:
        placeholders = ', '.join('?' for _ in contas)
        filtro_str = f"AND cc.NOME_CONTA IN ({placeholders})"
        filtro_params.extend(contas)

# ------------------------------
# Seção: Relatório de Contas a Receber
# ------------------------------
st.header("📥 Relatório de Contas a Receber")
st.info("Busca todas as contas a receber em aberto dentro do período de vencimento selecionado.")

if st.button("Gerar Dados de Contas a Receber"):
    query_receber = f"""
    SELECT
        p.NOME_PESSOA as cliente,
        cf.DATA_VENCIMENTO,
        cf.VALOR_NOMINAL,
        (cf.VALOR_NOMINAL - COALESCE(cf.VALOR_PAGO, 0)) as valor_pendente
    FROM CONTAS_FINANCEIRA cf
    JOIN PESSOAS p ON cf.IDPESSOA = p.IDPESSOA
    JOIN CONTAS_CORRENTE cc ON cf.IDLOJA = cc.IDLOJA
    WHERE cf.TIPO_CONTA IN ('RE', 'RP')
      AND cf.SITUACAO_CONTA = 'AB'
      AND cf.DATA_VENCIMENTO BETWEEN ? AND ?
      {filtro_str}
    ORDER BY cf.DATA_VENCIMENTO
    """
    params_receber = [data_inicio, data_fim] + filtro_params
    
    with st.spinner("Buscando contas a receber..."):
        df_receber = fetch_data(query_receber, params=params_receber)

    if not df_receber.empty:
        st.dataframe(df_receber, use_container_width=True)
        excel_data = to_excel(df_receber)
        st.download_button(
            label="📥 Fazer Download do Relatório",
            data=excel_data,
            file_name=f"relatorio_contas_a_receber_{datetime.now().strftime('%Y%m%d')}.xlsx",
            mime="application/vnd.ms-excel"
        )
    else:
        st.warning("Nenhuma conta a receber encontrada para os filtros selecionados.")

st.markdown("---")

# ------------------------------
# Seção: Relatório de Contas a Pagar
# ------------------------------
st.header("📤 Relatório de Contas a Pagar")
st.info("Busca todas as contas a pagar em aberto dentro do período de vencimento selecionado.")

if st.button("Gerar Dados de Contas a Pagar"):
    query_pagar = f"""
    SELECT
        p.NOME_PESSOA as fornecedor,
        cf.DATA_VENCIMENTO,
        cf.VALOR_NOMINAL,
        (cf.VALOR_NOMINAL - COALESCE(cf.VALOR_PAGO, 0)) as valor_pendente
    FROM CONTAS_FINANCEIRA cf
    JOIN PESSOAS p ON cf.IDPESSOA = p.IDPESSOA
    JOIN CONTAS_CORRENTE cc ON cf.IDLOJA = cc.IDLOJA
    WHERE cf.TIPO_CONTA = 'PA'
      AND cf.SITUACAO_CONTA = 'AB'
      AND cf.DATA_VENCIMENTO BETWEEN ? AND ?
      {filtro_str}
    ORDER BY cf.DATA_VENCIMENTO
    """
    params_pagar = [data_inicio, data_fim] + filtro_params
    
    with st.spinner("Buscando contas a pagar..."):
        df_pagar = fetch_data(query_pagar, params=params_pagar)
        
    if not df_pagar.empty:
        st.dataframe(df_pagar, use_container_width=True)
        excel_data = to_excel(df_pagar)
        st.download_button(
            label="📥 Fazer Download do Relatório",
            data=excel_data,
            file_name=f"relatorio_contas_a_pagar_{datetime.now().strftime('%Y%m%d')}.xlsx",
            mime="application/vnd.ms-excel"
        )
    else:
        st.warning("Nenhuma conta a pagar encontrada para os filtros selecionados.")

