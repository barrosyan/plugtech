import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta
# Remova 'from db_utils import get_connection, fetch_data' se for colar em um único arquivo
# Se db_utils for um arquivo separado, mantenha esta linha.
from db_utils import get_connection, fetch_data

# --- Configuração da Página ---
st.set_page_config(page_title="Inadimplência", layout="wide")
st.title("Análise de Inadimplência")

# Assumindo que get_connection e fetch_data estão definidos em db_utils
conn = get_connection()

# --- Mapeamento de Empresas e Contas ---
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

# --- Funções Auxiliares ---
def format_brl(valor):
    if not isinstance(valor, (int, float)): return "R$ 0,00"
    return f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

def percentual(valor, total):
    return (valor / total * 100) if total else 0

@st.cache_data(ttl=3600)
def cached_fetch_data(query, params):
    # Garante que a conexão seja passada para a função de busca
    return fetch_data(conn, query, params=params)

# --- Filtros na Sidebar ---
st.sidebar.header("Filtros da Página")
current_date = datetime.now()
current_year = current_date.year
current_month = current_date.month

ano_selecionado = st.sidebar.number_input("Selecione o Ano", min_value=2010, max_value=current_year + 5, value=current_year)
mes_selecionado = st.sidebar.selectbox("Selecione o Mês", options=range(1, 13), format_func=lambda x: f'{datetime(2000, x, 1).strftime("%B").capitalize()}', index=current_month - 1)
empresa_selecionada = st.sidebar.selectbox("Selecione a Empresa", ["Todas"] + list(EMPRESAS.keys()))

status_juridico = st.sidebar.selectbox(
    "Status Jurídico",
    ["Todos", "Apenas Negativados", "Excluir Negativados"],
    index=2 # Padrão para "Excluir Negativados"
)

# --- Construção da condição de filtro ---
filtro_empresa_condicao = ""
filtro_empresa_params = []
if empresa_selecionada != 'Todas':
    contas = EMPRESAS.get(empresa_selecionada)
    if contas:
        # Usando '?' como placeholder para SQL parameters
        placeholders = ', '.join('?' for _ in contas)
        filtro_empresa_condicao = f"AND cc.NOME_CONTA IN ({placeholders})"
        filtro_empresa_params.extend(contas)

# --- ALTERADO: Condição de filtro para o status jurídico ---
# A lógica agora usa cf.COD_CENTRO_CUSTO = 4240340
filtro_juridico_condicao = ""
if status_juridico == 'Apenas Negativados':
    # Inclui APENAS contas do centro de custo jurídico
    filtro_juridico_condicao = "AND cf.COD_CENTRO_CUSTO = 4240340"
elif status_juridico == 'Excluir Negativados':
    # Exclui contas do centro de custo jurídico (trata nulos como "não jurídico")
    filtro_juridico_condicao = "AND (cf.COD_CENTRO_CUSTO IS NULL OR cf.COD_CENTRO_CUSTO <> 4240340)"
# Se status_juridico == 'Todos', nenhum filtro de custo é adicionado.
# --- FIM DA ALTERAÇÃO ---


# --- Lógica de Datas ---
first_day_of_month = pd.Timestamp(ano_selecionado, mes_selecionado, 1).date()
last_day_of_month = pd.Timestamp(ano_selecionado, mes_selecionado, 1).to_period('M').end_time.date()
data_referencia = current_date.date()
data_limite_atraso = data_referencia - timedelta(days=5)
# REMOVIDO: data_limite_antiguidade = data_referencia - timedelta(days=548) # 1.5 anos

# --- QUERIES E CÁLCULO DOS KPIs ---

# 1. Faturamento no Mês (VENDAS) - SEM ALTERAÇÃO
query_faturamento = f"""
SELECT COALESCE(SUM(v.VALOR_VENDA), 0)
FROM VENDAS v
JOIN CONTAS_CORRENTE cc ON v.IDLOJA = cc.IDLOJA
WHERE v.DATA_CANCELAMENTO IS NULL
  AND v.DATA_VENDA BETWEEN ? AND ?
  {filtro_empresa_condicao}
"""
total_faturado = cached_fetch_data(query_faturamento, params=[first_day_of_month, last_day_of_month] + filtro_empresa_params).iloc[0,0]

# 2. Total de clientes com faturamento no mês (VENDAS) - SEM ALTERAÇÃO
query_total_clientes_mes = f"""
SELECT COUNT(DISTINCT v.IDPESSOA)
FROM VENDAS v
JOIN CONTAS_CORRENTE cc ON v.IDLOJA = cc.IDLOJA
WHERE v.DATA_CANCELAMENTO IS NULL
  AND v.DATA_VENDA BETWEEN ? AND ?
  {filtro_empresa_condicao}
"""
total_clientes_mes = cached_fetch_data(query_total_clientes_mes, params=[first_day_of_month, last_day_of_month] + filtro_empresa_params).iloc[0,0]


# --- NOVA LÓGICA: BUSCA ÚNICA PARA INADIMPLÊNCIA ---
# Esta query busca TODOS os dados de inadimplência (exceto < 5 dias)
# e servirá de base para TODOS os cálculos de inadimplência, conforme solicitado.
st.markdown("---")
st.header("Análise de Inadimplência")

query_base_inadimplencia = f"""
SELECT
    p.IDPESSOA,
    p.NOME_PESSOA as cliente,
    cf.DATA_VENCIMENTO as vencimento,
    (cf.VALOR_NOMINAL - COALESCE(cf.VALOR_PAGO, 0)) as valor
FROM CONTAS_FINANCEIRA cf
JOIN PESSOAS p ON cf.IDPESSOA = p.IDPESSOA
JOIN CONTAS_CORRENTE cc ON cf.IDLOJA = cc.IDLOJA
WHERE cf.TIPO_CONTA IN ('RE', 'RP')
  AND cf.SITUACAO_CONTA = 'AB'
  AND cf.DATA_VENCIMENTO < ? -- data_limite_atraso (vencidas há mais de 5 dias)
  -- O filtro de 1.5 anos (data_limite_antiguidade) foi REMOVIDO
  {filtro_empresa_condicao}
  {filtro_juridico_condicao} -- LÓGICA DO JURÍDICO APLICADA AQUI
"""
params_base = [data_limite_atraso] + filtro_empresa_params
df_base_inadimplencia = cached_fetch_data(query_base_inadimplencia, params=params_base)

# Converter colunas para tipos corretos (IMPORTANTE para pandas)
if not df_base_inadimplencia.empty:
    df_base_inadimplencia.columns = df_base_inadimplencia.columns.str.lower()
    df_base_inadimplencia['vencimento'] = pd.to_datetime(df_base_inadimplencia['vencimento'])
    df_base_inadimplencia['valor'] = pd.to_numeric(df_base_inadimplencia['valor'])
else:
    # Criar DF vazio com colunas corretas se a query não retornar nada
    df_base_inadimplencia = pd.DataFrame(columns=['idpessoa', 'cliente', 'vencimento', 'valor'])


# --- CÁLCULO DOS KPIs DE INADIMPLÊNCIA A PARTIR DO DF_BASE ---

# 3. Inadimplência (VALOR) NO MÊS SELECIONADO (calculado do df_base)
df_inadimplencia_mes = df_base_inadimplencia[
    (df_base_inadimplencia['vencimento'].dt.year == ano_selecionado) &
    (df_base_inadimplencia['vencimento'].dt.month == mes_selecionado)
]
inadimplencia_no_mes = df_inadimplencia_mes['valor'].sum()

# 4. Clientes Inadimplentes NO MÊS SELECIONADO (calculado do df_base)
clientes_inadimplentes_no_mes = df_inadimplencia_mes['idpessoa'].nunique()

# 5. Inadimplência ACUMULADA (VALOR) (calculado do df_base)
# Não há mais filtro de 1.5 anos, então é o valor total do df_base
total_inadimplente_acumulado = df_base_inadimplencia['valor'].sum()

# 6. Clientes Inadimplentes ACUMULADOS (calculado do df_base)
clientes_inadimplentes_acumulado = df_base_inadimplencia['idpessoa'].nunique()


# --- Exibição KPIs ---
st.markdown("##### Visão Financeira")
col1, col2, col3 = st.columns(3)
col1.metric("Faturado no Mês", format_brl(total_faturado))
col2.metric("Inadimplência no Mês", format_brl(inadimplencia_no_mes), f"{percentual(inadimplencia_no_mes, total_faturado):.1f}% do Faturamento", delta_color="inverse")
col3.metric("Inadimplência Acumulada", format_brl(total_inadimplente_acumulado), help="Valor total de contas vencidas há mais de 5 dias (sem limite de data).")

st.markdown("##### Visão de Clientes")
col4, col5, col6 = st.columns(3)
col4.metric("Nº de Clientes no Mês", f"{total_clientes_mes}")
col5.metric("Clientes Inadimplentes no Mês", f"{clientes_inadimplentes_no_mes}", f"{percentual(clientes_inadimplentes_no_mes, total_clientes_mes):.1f}% dos Clientes", delta_color="inverse")
col6.metric("Clientes Inadimplentes (Acum.)", f"{clientes_inadimplentes_acumulado}", help="Nº de clientes únicos com contas vencidas há mais de 5 dias (sem limite de data).")


# --- Gráficos (Calculados a partir do df_base) ---
st.markdown("---")
st.header(f"Análise Mensal da Inadimplência em {ano_selecionado}")
col_valor, col_clientes = st.columns(2)

# Filtra o DF base apenas para o ano selecionado (para ambos os gráficos)
df_grafico_anual = df_base_inadimplencia[
    df_base_inadimplencia['vencimento'].dt.year == ano_selecionado
].copy()


with col_valor:
    # GRÁFICO 1: Valor Inadimplente por Mês (calculado do df_base)
    if not df_grafico_anual.empty:
        df_grafico_anual['mes'] = df_grafico_anual['vencimento'].dt.month
        df_temporal_valor = df_grafico_anual.groupby('mes')['valor'].sum().reset_index()
        df_temporal_valor.columns = ['mes', 'valor_inad']

        # Reindexar para garantir todos os 12 meses
        df_temporal_valor = df_temporal_valor.set_index('mes').reindex(range(1, 13), fill_value=0).reset_index()
        df_temporal_valor['mes_nome'] = df_temporal_valor['mes'].apply(lambda x: datetime(2000, x, 1).strftime("%b").capitalize())
        df_temporal_valor['valor_acumulado'] = df_temporal_valor['valor_inad'].cumsum()

        fig_temporal = go.Figure()
        # Adiciona barras
        fig_temporal.add_trace(go.Bar(
            x=df_temporal_valor['mes_nome'],
            y=df_temporal_valor['valor_inad'],
            name='Valor Inadimplente no Mês',
            text=df_temporal_valor['valor_inad'].apply(format_brl),
            textposition='outside'
        ))
        # Adiciona linha
        fig_temporal.add_trace(go.Scatter(
            x=df_temporal_valor['mes_nome'],
            y=df_temporal_valor['valor_acumulado'],
            name='Total Acumulado',
            mode='lines+markers',
            yaxis='y2'
        ))

        fig_temporal.update_layout(
            title='Valor Inadimplente por Mês e Acumulado',
            xaxis_title='Mês de Vencimento',
            yaxis_title='Valor Inadimplente no Mês (R$)',
            yaxis2=dict(
                title='Valor Acumulado (R$)',
                overlaying='y',
                side='right'
            ),
            legend=dict(x=0.01, y=0.99, bordercolor='Gainsboro', borderwidth=1)
        )
        st.plotly_chart(fig_temporal, use_container_width=True)
    else:
        st.write("Nenhum dado de inadimplência encontrado para o ano selecionado.")


with col_clientes:
    # GRÁFICO 2: Clientes Inadimplentes por Mês (calculado do df_base)
    if not df_grafico_anual.empty:
        # Reutiliza o df_grafico_anual (que já tem a coluna 'mes')
        df_temporal_clientes = df_grafico_anual.groupby('mes')['idpessoa'].nunique().reset_index()
        df_temporal_clientes.columns = ['mes', 'qtd_clientes']

        # Reindexar para garantir todos os 12 meses
        df_temporal_clientes = df_temporal_clientes.set_index('mes').reindex(range(1, 13), fill_value=0).reset_index()
        df_temporal_clientes['mes_nome'] = df_temporal_clientes['mes'].apply(lambda x: datetime(2000, x, 1).strftime("%b").capitalize())
        
        fig_clientes = px.bar(df_temporal_clientes, x='mes_nome', y='qtd_clientes', text_auto=True, labels={'mes_nome': 'Mês de Vencimento', 'qtd_clientes': 'Nº de Clientes'}, title='Clientes Inadimplentes por Mês')
        fig_clientes.update_traces(textangle=0, textposition="outside")
        st.plotly_chart(fig_clientes, use_container_width=True)
    else:
        st.write("Nenhum dado de inadimplência encontrado para o ano selecionado.")

# --- Tabela detalhada (a partir do df_base) ---
st.markdown("---")
st.subheader("Detalhes da Inadimplência (Contas Vencidas e Não Pagas)")

# A query_tabela não é mais necessária, usamos o df_base_inadimplencia

if not df_base_inadimplencia.empty:
    # Criar a df_tabela a partir do df_base
    df_tabela = df_base_inadimplencia.copy()
    
    # Calcular dias_atraso
    df_tabela['dias_atraso'] = (pd.to_datetime(data_referencia) - df_tabela['vencimento']).dt.days
    
    # Ordenar
    df_tabela = df_tabela.sort_values(by='dias_atraso', ascending=False)
    
    # Selecionar e renomear colunas para exibição
    df_tabela_display = df_tabela[['cliente', 'vencimento', 'dias_atraso', 'valor']]

    # O total já foi calculado como total_inadimplente_acumulado
    if total_inadimplente_acumulado > 0:
        df_tabela_display['% do total'] = (df_tabela_display['valor'] / total_inadimplente_acumulado * 100)
    else:
        df_tabela_display['% do total'] = 0
    
    # MODIFICADO: Usando column_config para formatar valor e permitir ordenação
    st.dataframe(
        df_tabela_display, 
        use_container_width=True,
        column_config={
            "vencimento": st.column_config.DateColumn(
                "Vencimento",
                format="DD/MM/YYYY"
            ),
            "valor": st.column_config.NumberColumn(
                "Valor",
                format="R$ %.2f"
            ),
            "% do total": st.column_config.NumberColumn(
                "% do Total",
                format="%.2f%%"
            )
        }
    )
else:
    st.write("Nenhuma conta inadimplente encontrada com os critérios selecionados.")
