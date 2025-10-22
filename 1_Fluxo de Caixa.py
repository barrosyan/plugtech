import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import datetime, timedelta
# Assumindo que db_utils.py está no mesmo diretório
from db_utils import get_connection, fetch_data

st.set_page_config(page_title="Financeiro", layout="wide")
st.title("Análise Financeira")

conn = get_connection()

# --- Mapeamento de Empresas e suas contas ---
EMPRESAS = {
    "Plugtech Brasil": [
        'BB PLUG BRASIL RF', 'BNB PLUG BRASIL 8299', 'BNB ES FI PLUG BRASI',
        'BB PLUG BRASIL', 'BNB RS FI PLUG BRASI', 'BNB PLUG BRASIL13815',
        'BNB PLUG BRASIL13910', 'CEF PLUG BRASIL', 'CEF AP PLUG BRASIL',
        'ADM PLUG BRASIL', 'PERDA CONT PLUG BRAS', 'PJBANK PLUGTECH BRAS',
        'CARTAO 9412 PLUG BRA', 'F RESERVA P BRASIL'
    ],
    "Plugtech Gestão": [
        'BB PLUG GESTAO RF', 'BB PLUG GESTAO', 'SICRED CAPITAL GESTA',
        'ADM PLUG GESTAO', 'BNB PLUG GESTAO32495', 'PJBANK PLUGTECH GEST',
        'SICRED PLUG GESTAO'
    ],
    "Plugtech Serviços": [
        'BB PLUG SERVICOS RF', 'BB PLUG SERVICOS', 'BNB PLUG SERV 26551',
        'BNB PLUG SERVIC28454', 'BNB FI AT PLUG SERVI', 'CEF PLUG SERVICOS',
        'CEF AP PLUG SERVICOS', 'TESOURARIA PLUG SERV', 'ADM PLUG SERVICOS',
        'PERDA CONT PLUG SERV', 'CARTAO 3948 PLUG SER', 'PJBANK PLUGTECG SERV',
        'F RESERVA P SERVICOS'
    ]
}

# --- Função de formatação BRL ---
def format_brl(valor):
    if not isinstance(valor, (int, float)): return "R$ 0,00"
    return f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

# --- Filtros na Sidebar ---
st.sidebar.header("Filtros da Página")
data_inicio = st.sidebar.date_input("Data de Início", datetime.now().date() - timedelta(days=30))
data_fim = st.sidebar.date_input("Data de Fim", datetime.now().date())

empresa_selecionada = st.sidebar.selectbox("Empresa", ["Todas"] + list(EMPRESAS.keys()))

# NOVO: Filtro para contas no jurídico
status_juridico = st.sidebar.selectbox(
    "Status Jurídico",
    ["Todos", "Apenas Negativados", "Excluir Negativados"],
    index=2 # Padrão para "Excluir Negativados"
)


# --- Construção da condição de filtro dinâmica ---
filtro_contas_corrente_condicao = []
filtro_contas_corrente_params = []

filtro_contas_financeira_condicao = []
filtro_contas_financeira_params = []


if empresa_selecionada != 'Todas':
    contas = EMPRESAS.get(empresa_selecionada)
    if contas:
        placeholders = ', '.join('?' for _ in contas)
        # Filtro para queries na CONTAS_CORRENTE
        filtro_contas_corrente_condicao.append(f"cc.NOME_CONTA IN ({placeholders})")
        filtro_contas_corrente_params.extend(contas)
        # Filtro para queries na CONTAS_FINANCEIRA (que usa join com CONTAS_CORRENTE)
        filtro_contas_financeira_condicao.append(f"cc.NOME_CONTA IN ({placeholders})")
        filtro_contas_financeira_params.extend(contas)

# --- ALTERADO: Adiciona condição do filtro jurídico para CONTAS_FINANCEIRA ---
# A lógica agora usa cf.COD_CENTRO_CUSTO = 4240340
if status_juridico == 'Apenas Negativados':
    # Inclui APENAS contas do centro de custo jurídico
    filtro_contas_financeira_condicao.append("cf.COD_CENTRO_CUSTO = 4240340")
elif status_juridico == 'Excluir Negativados':
    # Exclui contas do centro de custo jurídico (trata nulos como "não jurídico")
    filtro_contas_financeira_condicao.append("(cf.COD_CENTRO_CUSTO IS NULL OR cf.COD_CENTRO_CUSTO <> 4240340)")
# Se status_juridico == 'Todos', nenhum filtro de custo é adicionado.
# --- FIM DA ALTERAÇÃO ---

filtro_contas_corrente_condicao.append("cc.IDCONTA_CORRENTE <> 32 AND cc.IDCONTA_CORRENTE <> 33")

# Constrói as strings de filtro final
filtro_cc_str = " AND ".join(filtro_contas_corrente_condicao) if filtro_contas_corrente_condicao else ""
filtro_cf_str = " AND ".join(filtro_contas_financeira_condicao) if filtro_contas_financeira_condicao else ""


# --- Função para buscar dados de KPI ---
@st.cache_data(ttl=3600)
def calcular_kpi(query, params):
    df = fetch_data(conn, query, params=params)
    return df.iloc[0,0] if not df.empty and pd.notna(df.iloc[0,0]) else 0

# --- KPIs Financeiros ---
col1, col2, col3, col4 = st.columns(4)

# KPI 1: Saldo Final - ALTERADO
query_saldo = f"""
SELECT COALESCE(SUM(COALESCE(cc.SALDO_FECHAMENTO, 0) + COALESCE(cc.SALDO_DINHEIRO, 0) + COALESCE(cc.SALDO_CHEQUE, 0)), 0)
FROM CONTAS_CORRENTE cc
{ "WHERE " + filtro_cc_str if filtro_cc_str else ""}
"""
saldo_final = calcular_kpi(query_saldo, filtro_contas_corrente_params)
col1.metric("Saldo na Conta", format_brl(saldo_final), help="Saldo (Fechamento + Dinheiro + Cheque) somado de todas as contas, baseado nos filtros.")

# KPI 2: Total a Receber (MODIFICADO: removido valor zero)
query_receber = f"""
SELECT COALESCE(SUM(cf.VALOR_NOMINAL - COALESCE(cf.VALOR_PAGO,0)),0)
FROM CONTAS_FINANCEIRA cf
JOIN CONTAS_CORRENTE cc ON cf.IDLOJA = cc.IDLOJA
WHERE cf.TIPO_CONTA IN('RE','RP') AND cf.SITUACAO_CONTA='AB' AND cf.DATA_VENCIMENTO BETWEEN ? AND ?
  AND (cf.VALOR_NOMINAL - COALESCE(cf.VALOR_PAGO,0)) > 0
  { "AND " + filtro_cf_str if filtro_cf_str else ""}
"""
total_a_receber = calcular_kpi(query_receber, [data_inicio, data_fim] + filtro_contas_financeira_params)
col2.metric("Contas a Receber", format_brl(total_a_receber))

# KPI 3: Total a Pagar (MODIFICADO: removido valor zero)
query_pagar = f"""
SELECT COALESCE(SUM(cf.VALOR_NOMINAL - COALESCE(cf.VALOR_PAGO,0)),0)
FROM CONTAS_FINANCEIRA cf
JOIN CONTAS_CORRENTE cc ON cf.IDLOJA = cc.IDLOJA
WHERE cf.TIPO_CONTA='PA' AND cf.SITUACAO_CONTA='AB' AND cf.DATA_VENCimento BETWEEN ? AND ?
  AND (cf.VALOR_NOMINAL - COALESCE(cf.VALOR_PAGO,0)) > 0
  { "AND " + filtro_cf_str if filtro_cf_str else ""}
"""
total_a_pagar = calcular_kpi(query_pagar, [data_inicio, data_fim] + filtro_contas_financeira_params)
col3.metric("Contas a Pagar", format_brl(total_a_pagar))

# KPI 4: Saldo Operacional
saldo_operacional = saldo_final + total_a_receber - total_a_pagar
col4.metric("Saldo Operacional", format_brl(saldo_operacional), help="Saldo na Conta + Contas a Receber - Contas a Pagar")

st.markdown("---")

# --- GRÁFICO NOVO: Entradas vs Saídas ---
st.subheader("Balanço de Entradas e Saídas")
query_balanco = f"""
SELECT
    lb.DATA_OPERACAO,
    COALESCE(SUM(CASE WHEN lb.TIPO_LANCAMENTO = 'E' THEN lb.VALOR_LANCAMENTO ELSE 0 END), 0) AS Entradas,
    COALESCE(SUM(CASE WHEN lb.TIPO_LANCAMENTO = 'S' THEN lb.VALOR_LANCAMENTO ELSE 0 END), 0) AS Saidas
FROM LANCAMENTOS_BANCARIO lb
JOIN CONTAS_CORRENTE cc ON lb.IDLOJA = cc.IDLOJA
WHERE lb.DATA_OPERACAO BETWEEN ? AND ? { "AND " + filtro_cc_str if filtro_cc_str else ""}
GROUP BY lb.DATA_OPERACAO
ORDER BY lb.DATA_OPERACAO
"""
df_balanco = fetch_data(conn, query_balanco, [data_inicio, data_fim] + filtro_contas_corrente_params)

if not df_balanco.empty:
    df_balanco.columns = df_balanco.columns.str.lower()
    df_balanco['data_operacao'] = pd.to_datetime(df_balanco['data_operacao'])

    # Garante que todos os dias do intervalo apareçam
    todas_as_datas = pd.date_range(start=data_inicio, end=data_fim)
    df_completo = pd.DataFrame(todas_as_datas, columns=['data_operacao'])
    df_balanco = pd.merge(df_completo, df_balanco, on='data_operacao', how='left').fillna(0)
    
    # Transforma 'saidas' em valor negativo para plotagem
    df_balanco['saidas'] = -df_balanco['saidas']
    
    # Prepara o dataframe para o gráfico (formato longo)
    df_plot = df_balanco.melt(
        id_vars='data_operacao',
        value_vars=['entradas', 'saidas'],
        var_name='tipo',
        value_name='valor'
    )
    # Remove os dias com valor 0 para não poluir o gráfico
    df_plot = df_plot[df_plot['valor'] != 0]

    fig_balanco = px.bar(
        df_plot,
        x='data_operacao',
        y='valor',
        color='tipo',
        title='Entradas vs. Saídas Diárias',
        labels={'data_operacao': 'Data', 'valor': 'Valor (R$)', 'tipo': 'Tipo de Lançamento'},
        color_discrete_map={'entradas': '#2ca02c', 'saidas': '#d62728'},
        barmode='relative',
        text=df_plot['valor'].apply(format_brl)
    )

    fig_balanco.update_traces(textposition='auto')
    fig_balanco.update_layout(
        showlegend=True,
        xaxis=dict(
            tickformat='%d-%m-%Y', # ALTERADO: formato de data
            title='Data',
            type='date'
        ),
        yaxis=dict(title='Valor (R$)')
    )

    st.plotly_chart(fig_balanco, use_container_width=True)
else:
    st.info("Não há dados de lançamentos bancários para o período selecionado.")

st.markdown("---")

# --- Tabelas lado a lado: Contas a Receber e Contas a Pagar ---
col_receber, col_pagar = st.columns(2)

with col_receber:
    st.markdown("### Contas a Receber Detalhadas")
    # MODIFICADO: Adicionado filtro (cf.VALOR_NOMINAL - COALESCE(cf.VALOR_PAGO,0)) > 0
    query_tabela_receber = f"""
    SELECT cf.DATA_VENCIMENTO,
            p.NOME_PESSOA AS cliente,
            (cf.VALOR_NOMINAL - COALESCE(cf.VALOR_PAGO,0)) AS valor_pendente
    FROM CONTAS_FINANCEIRA cf
    JOIN PESSOAS p ON cf.IDPESSOA = p.IDPESSOA
    JOIN CONTAS_CORRENTE cc ON cf.IDLOJA = cc.IDLOJA
    WHERE cf.TIPO_CONTA IN('RE','RP')
      AND cf.DATA_VENCIMENTO BETWEEN ? AND ?
      AND (cf.VALOR_NOMINAL - COALESCE(cf.VALOR_PAGO,0)) > 0
      { "AND " + filtro_cf_str if filtro_cf_str else ""}
    ORDER BY cf.DATA_VENCIMENTO
    """
    df_tabela_receber = fetch_data(conn, query_tabela_receber, [data_inicio, data_fim] + filtro_contas_financeira_params)
    if not df_tabela_receber.empty:
        df_tabela_receber.columns = df_tabela_receber.columns.str.lower()
        # ALTERADO: Formato de data
        df_tabela_receber['data_vencimento'] = pd.to_datetime(df_tabela_receber['data_vencimento']).dt.strftime('%d-%m-%Y')
        # REMOVIDA: Formatação manual do valor_pendente
        # df_tabela_receber['valor_pendente'] = df_tabela_receber['valor_pendente'].apply(format_brl)
    
    # MODIFICADO: Usando column_config para formatar
    st.dataframe(
        df_tabela_receber,
        use_container_width=True,
        hide_index=True,
        column_config={
            "valor_pendente": st.column_config.NumberColumn(
                "Valor Pendente",
                format="R$ %.2f"
            )
        }
    )

with col_pagar:
    st.markdown("### Contas a Pagar Detalhadas")
    # MODIFICADO: Exibindo VALOR_NOMINAL, mas mantendo o filtro de valor pendente > 0
    query_tabela_pagar = f"""
    SELECT cf.DATA_VENCIMENTO,
            p.NOME_PESSOA AS fornecedor,
            cf.VALOR_NOMINAL AS valor_nominal -- ALTERADO DE VOLTA PARA VALOR_NOMINAL
    FROM CONTAS_FINANCEIRA cf
    JOIN PESSOAS p ON cf.IDPESSOA = p.IDPESSOA
    JOIN CONTAS_CORRENTE cc ON cf.IDLOJA = cc.IDLOJA
    WHERE cf.TIPO_CONTA='PA'
      AND cf.DATA_VENCIMENTO BETWEEN ? AND ?
      AND (cf.VALOR_NOMINAL - COALESCE(cf.VALOR_PAGO,0)) > 0 -- FILTRO DE PENDENTE > 0 MANTIDO
      { "AND " + filtro_cf_str if filtro_cf_str else ""}
    ORDER BY cf.DATA_VENCIMENTO
    """
    df_tabela_pagar = fetch_data(conn, query_tabela_pagar, [data_inicio, data_fim] + filtro_contas_financeira_params)
    if not df_tabela_pagar.empty:
        df_tabela_pagar.columns = df_tabela_pagar.columns.str.lower()
        # ALTERADO: Formato de data
        df_tabela_pagar['data_vencimento'] = pd.to_datetime(df_tabela_pagar['data_vencimento']).dt.strftime('%d-%m-%Y')
        # REMOVIDA: Formatação manual do valor_nominal
        # df_tabela_pagar['valor_nominal'] = df_tabela_pagar['valor_nominal'].apply(format_brl)
    
    # MODIFICADO: Usando column_config para formatar
    st.dataframe(
        df_tabela_pagar,
        use_container_width=True,
        hide_index=True,
        column_config={
            "valor_nominal": st.column_config.NumberColumn(
                "Valor Nominal",
                format="R$ %.2f"
            )
        }
    )

