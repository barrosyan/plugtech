import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime
from pandas.tseries.offsets import MonthEnd
from db_utils import get_connection
from io import BytesIO

st.set_page_config(page_title="Visão Geral e Análise Anual", layout="wide")
st.title("Visão Geral e Análise Anual")

# --- Mapeamentos ---
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
EQUIPMENT_CATEGORIES_MAP = {
    "Impressoras Coloridas": "{col} LIKE '%COLOR%'",
    "Impressoras Monocromáticas": "({col} LIKE '%MONO%' AND {col} NOT LIKE '%COLOR%')",
    "Desktop": "({col} LIKE '%DESKTOP%' OR {col} LIKE '%CPU%')",
    "Monitor": "{col} LIKE '%MONITOR%'",
    "Notebook": "{col} LIKE '%NOTEBOOK%'",
    "Outros": "({col} NOT LIKE '%COLOR%' AND {col} NOT LIKE '%MONO%' AND {col} NOT LIKE '%DESKTOP%' AND {col} NOT LIKE '%CPU%' AND {col} NOT LIKE '%MONITOR%' AND {col} NOT LIKE '%NOTEBOOK%')"
}
SITUACAO_MAP = { 'AB': 'Aberto', 'BL': 'Bloqueado', 'CA': 'Cancelado' }
MESES_ABREV = { 1: 'JAN', 2: 'FEV', 3: 'MAR', 4: 'ABR', 5: 'MAI', 6: 'JUN', 7: 'JUL', 8: 'AGO', 9: 'SET', 10: 'OUT', 11: 'NOV', 12: 'DEZ' }

# --- Conexão e Funções Auxiliares ---
conn = get_connection()

def fetch_data_safely(conn, query, params=(), expected_columns=None):
    try:
        df = pd.read_sql_query(query, conn, params=params)
        if df.empty and expected_columns:
            return pd.DataFrame(columns=expected_columns)
        return df
    except Exception as e:
        st.error(f"Erro ao executar a query: {e}")
        st.code(query)
        if expected_columns:
            return pd.DataFrame(columns=expected_columns)
        return pd.DataFrame()

@st.cache_data
def to_excel(dfs_dict):
    output = BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        for sheet_name, df in dfs_dict.items():
            df.to_excel(writer, sheet_name=sheet_name, index=False)
    return output.getvalue()

# --- Sidebar ---
st.sidebar.header("Filtros")
empresas_selecionadas = st.sidebar.multiselect("Selecione a(s) Empresa(s)", options=list(EMPRESAS.keys()), default=list(EMPRESAS.keys()))
equip_selecionados = st.sidebar.multiselect("Selecione o(s) Equipamento(s)", options=list(EQUIPMENT_CATEGORIES_MAP.keys()), default=list(EQUIPMENT_CATEGORIES_MAP.keys()))
situacoes_selecionadas = st.sidebar.multiselect("Selecione o Tipo de Contrato", options=list(SITUACAO_MAP.keys()), format_func=lambda x: SITUACAO_MAP[x], default=['AB'])

data_hoje = datetime.now()
ano_atual = data_hoje.year
ano_selecionado = st.sidebar.number_input("Ano", min_value=2010, max_value=ano_atual + 5, value=ano_atual)

# --- Funções de busca de dados ---
@st.cache_data(ttl=3600)
def get_product_ids_by_category(categories):
    if not categories or len(categories) == len(EQUIPMENT_CATEGORIES_MAP): return []
    where_clauses = [EQUIPMENT_CATEGORIES_MAP.get(cat, "").format(col='DESCRICAO_PRODUTO') for cat in categories]
    where_clauses = [clause for clause in where_clauses if clause]
    if not where_clauses: return []
    query = f"SELECT IDPRODUTO FROM PRODUTOS WHERE {' OR '.join(where_clauses)}"
    df = fetch_data_safely(conn, query)
    return df['IDPRODUTO'].tolist() if not df.empty else []

def build_where_and_params(empresas, situacoes, product_ids=None, table_alias_map=None):
    params, where_clauses, joins = [], [], []
    if table_alias_map is None: table_alias_map = {}
    conta_alias = table_alias_map.get('conta', 'c')
    contrato_alias = table_alias_map.get('contrato', 'c')
    if empresas:
        contas = [conta for emp in empresas for conta in EMPRESAS.get(emp, [])]
        if contas:
            placeholders = ', '.join('?' for _ in contas)
            joins.append(f"JOIN CONTAS_CORRENTE cc ON {conta_alias}.IDLOJA = cc.IDLOJA")
            where_clauses.append(f"cc.NOME_CONTA IN ({placeholders})")
            params.extend(contas)
    if situacoes:
        placeholders = ', '.join('?' for _ in situacoes)
        where_clauses.append(f"{contrato_alias}.SITUACAO IN ({placeholders})")
        params.extend(situacoes)
    if product_ids:
        joins.append(f"JOIN CONTRATOS_EQUIPAMENTO ce ON {contrato_alias}.IDCONTRATO = ce.IDCONTRATO")
        joins.append("JOIN EQUIPAMENTOS_ITENS ei ON ce.IDEQUIPAMENTO_ITEM = ei.IDEQUIPAMENTO_ITEM")
        placeholders = ', '.join('?' for _ in product_ids)
        where_clauses.append(f"ei.IDPRODUTO IN ({placeholders})")
        params.extend(product_ids)
    return params, where_clauses, list(dict.fromkeys(joins))

def get_faturamento(year, empresas, situacoes):
    base_query = "SELECT SUM(v.VALOR_VENDA) AS VALOR FROM VENDAS v JOIN CONTRATOS c ON v.IDCONTRATO = c.IDCONTRATO"
    params, where, joins = build_where_and_params(empresas, situacoes, table_alias_map={'conta': 'v', 'contrato': 'c'})
    where.append("v.DATA_CANCELAMENTO IS NULL")
    if year:
        where.append("EXTRACT(YEAR FROM v.DATA_VENDA) = ?")
        params.append(year)
    query = base_query + " " + " ".join(joins) + " WHERE " + " AND ".join(where)
    df = fetch_data_safely(conn, query, tuple(params))
    return df['VALOR'].iloc[0] if not df.empty and pd.notna(df['VALOR'].iloc[0]) else 0

def get_faturamento_mensal(year, empresas, situacoes):
    query = "SELECT EXTRACT(MONTH FROM v.DATA_VENDA) AS MES, SUM(CASE WHEN EXTRACT(YEAR FROM v.DATA_VENDA) = ? THEN v.VALOR_VENDA ELSE 0 END) AS FAT_ATUAL, SUM(CASE WHEN EXTRACT(YEAR FROM v.DATA_VENDA) = ? THEN v.VALOR_VENDA ELSE 0 END) AS FAT_ANTERIOR FROM VENDAS v JOIN CONTRATOS c ON v.IDCONTRATO = c.IDCONTRATO"
    params, where, joins = build_where_and_params(empresas, situacoes, table_alias_map={'conta': 'v', 'contrato': 'c'})
    params_final = [year, year - 1] + params
    where.append("v.DATA_CANCELAMENTO IS NULL")
    query += " " + " ".join(joins) + " WHERE " + " AND ".join(where)
    query += " GROUP BY MES ORDER BY MES"
    return fetch_data_safely(conn, query, tuple(params_final), expected_columns=['MES', 'FAT_ATUAL', 'FAT_ANTERIOR'])

def calcular_variacao(atual, anterior):
    if anterior is None or anterior == 0: return 0.0
    if atual is None: return -100.0
    return ((atual - anterior) / anterior) * 100

# --- Lógica Principal e de Faturamento ---
ids_produto_selecionados = get_product_ids_by_category(equip_selecionados)
faturamento_ano_inteiro_anterior = get_faturamento(ano_selecionado - 1, empresas_selecionadas, situacoes_selecionadas)
faturamento_acumulado_ano_selecionado = get_faturamento(ano_selecionado, empresas_selecionadas, situacoes_selecionadas)
df_fat_mensal = get_faturamento_mensal(ano_selecionado, empresas_selecionadas, situacoes_selecionadas)

meses_df = pd.DataFrame({'MES': range(1, 13)})
df_fat_mensal = pd.merge(meses_df, df_fat_mensal, on='MES', how='left').fillna(0)
df_fat_mensal['MES_ABREV'] = df_fat_mensal['MES'].map(MESES_ABREV)

if data_hoje.date() < (data_hoje.replace(day=1) + MonthEnd(1)).date():
    meses_fechados = data_hoje.month - 1
else:
    meses_fechados = data_hoje.month

tendencia_fim_ano, media_mensal_realizada = faturamento_acumulado_ano_selecionado, 0
if ano_selecionado == ano_atual and meses_fechados > 0:
    faturamento_meses_fechados = df_fat_mensal[df_fat_mensal['MES'] <= meses_fechados]['FAT_ATUAL'].sum()
    media_mensal_realizada = faturamento_meses_fechados / meses_fechados
    tendencia_fim_ano = faturamento_meses_fechados + (media_mensal_realizada * (12 - meses_fechados))

faturamento_acumulado_pytd = 0
if meses_fechados > 0:
    faturamento_acumulado_pytd = df_fat_mensal[df_fat_mensal['MES'] <= meses_fechados]['FAT_ANTERIOR'].sum()

faturamento_mes_anterior, faturamento_mes_anterior_py = 0, 0
mes_anterior = meses_fechados
if mes_anterior > 0:
    faturamento_mes_anterior = df_fat_mensal[df_fat_mensal['MES'] == mes_anterior]['FAT_ATUAL'].iloc[0]
    faturamento_mes_anterior_py = df_fat_mensal[df_fat_mensal['MES'] == mes_anterior]['FAT_ANTERIOR'].iloc[0]

# --- Função para formatar valores em k, M, B ---
def formatar_valor_abreviado(valor):
    if abs(valor) >= 1_000_000_000:
        return f"{valor/1_000_000_000:.1f}B"
    elif abs(valor) >= 1_000_000:
        return f"{valor/1_000_000:.1f}M"
    elif abs(valor) >= 1_000:
        return f"{valor/1_000:.0f}k"
    else:
        return f"{valor:.0f}"

# --- Layout e Gráficos de Faturamento ---
st.subheader(f"Análise de Faturamento: {ano_selecionado}")
kpi1, kpi2, kpi3 = st.columns(3)

kpi1.metric(
    label=f"Faturamento Acumulado {ano_selecionado}",
    value=f"R$ {formatar_valor_abreviado(faturamento_acumulado_ano_selecionado)}",
    delta=f"{calcular_variacao(faturamento_acumulado_ano_selecionado, faturamento_acumulado_pytd):.1f}% vs mesmo período de {ano_selecionado-1}"
)

if mes_anterior > 0:
    kpi2.metric(
        label=f"Faturamento {MESES_ABREV[mes_anterior].capitalize()} {ano_selecionado}",
        value=f"R$ {formatar_valor_abreviado(faturamento_mes_anterior)}",
        delta=f"{calcular_variacao(faturamento_mes_anterior, faturamento_mes_anterior_py):.1f}% vs {MESES_ABREV[mes_anterior].capitalize()} {ano_selecionado-1}"
    )
else:
    kpi2.metric(label="Faturamento Mês Anterior", value="N/A", delta="Aguardando fechamento do primeiro mês.")

kpi3.metric(
    label="Tendência até fim de ano",
    value=f"R$ {formatar_valor_abreviado(tendencia_fim_ano)}",
    delta=f"{calcular_variacao(tendencia_fim_ano, faturamento_ano_inteiro_anterior):.1f}% vs total de {ano_selecionado-1}"
)

col_graph_total, col_graph_mensal = st.columns([1, 2])
with col_graph_total:
    variacao_tendencia = calcular_variacao(tendencia_fim_ano, faturamento_ano_inteiro_anterior)
    cor_tendencia = 'green' if variacao_tendencia >= 0 else 'red'
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=['Comparativo'],
        y=[faturamento_ano_inteiro_anterior],
        name=f"{ano_selecionado - 1}",
        text=[f"R$ {formatar_valor_abreviado(faturamento_ano_inteiro_anterior)}"],
        textposition="outside",
        marker_color='lightslategray'
    ))
    fig.add_trace(go.Bar(
        x=['Comparativo'],
        y=[tendencia_fim_ano],
        name=f"{ano_selecionado} (Tendência)",
        text=[f"R$ {formatar_valor_abreviado(tendencia_fim_ano)}"],
        textposition="outside",
        marker_color=cor_tendencia
    ))
    if faturamento_ano_inteiro_anterior > 0 or tendencia_fim_ano > 0:
        fig.add_annotation(
            x='Comparativo',
            y=max(tendencia_fim_ano, faturamento_ano_inteiro_anterior) * 1.2,
            text=f"Variação: {variacao_tendencia:.1f}%",
            showarrow=False,
            font=dict(size=14, color=cor_tendencia)
        )
    fig.update_layout(
        title="Comparativo Anual",
        yaxis_title="Faturamento (R$)",
        xaxis_title="",
        barmode='group',
        showlegend=True,
        xaxis=dict(tickvals=[])
    )
    st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False})

with col_graph_mensal:
    fig = go.Figure()
    fig.add_trace(go.Bar(
        name=f'{ano_selecionado - 1}',
        x=df_fat_mensal['MES_ABREV'],
        y=df_fat_mensal['FAT_ANTERIOR'],
        marker_color='lightslategray',
        text=df_fat_mensal['FAT_ANTERIOR'].apply(lambda x: f'R$ {formatar_valor_abreviado(x)}' if x > 0 else ''),
        textposition='outside'
    ))

    if ano_selecionado == ano_atual:
        df_fat_mensal['FAT_EXIBICAO'] = df_fat_mensal.apply(
            lambda row: media_mensal_realizada if row['MES'] > meses_fechados else row['FAT_ATUAL'], axis=1
        )
        colors = ['cornflowerblue'] * meses_fechados + ['lightskyblue'] * (12 - meses_fechados)
        fig.add_trace(go.Bar(
            name=f'{ano_selecionado}',
            x=df_fat_mensal['MES_ABREV'],
            y=df_fat_mensal['FAT_EXIBICAO'],
            marker_color=colors,
            text=df_fat_mensal['FAT_EXIBICAO'].apply(lambda x: f'R$ {formatar_valor_abreviado(x)}' if x > 0 else ''),
            textposition='outside'
        ))
    else:
        fig.add_trace(go.Bar(
            name=f'{ano_selecionado}',
            x=df_fat_mensal['MES_ABREV'],
            y=df_fat_mensal['FAT_ATUAL'],
            marker_color='cornflowerblue',
            text=df_fat_mensal['FAT_ATUAL'].apply(lambda x: f'R$ {formatar_valor_abreviado(x)}' if x > 0 else ''),
            textposition='outside'
        ))

    fig.update_layout(
        barmode='group',
        xaxis_title='Mês',
        yaxis_title='Faturamento (R$)',
        title="Faturamento Mensal Comparativo"
    )
    st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False})

    if ano_selecionado == ano_atual:
        st.info("As barras mais claras representam uma tendência baseada na média dos meses fechados.")

st.markdown("---")


# --- Novos Gráficos de Pizza ---
st.subheader("Análise Detalhada por Setor e Equipamento")
mes_pizza = st.selectbox("Selecione o Mês para Análise", options=[0] + list(range(1, 13)), format_func=lambda x: 'Ano Inteiro' if x == 0 else MESES_ABREV[x])

def get_faturamento_por_setor(year, month, empresas, situacoes):
    query = "SELECT CASE p.IDGRUPO_PESSOA WHEN 8 THEN 'Público' WHEN 9 THEN 'Privado' ELSE 'Outros' END AS SETOR, SUM(v.VALOR_VENDA) AS FATURAMENTO FROM VENDAS v JOIN CONTRATOS c ON v.IDCONTRATO = c.IDCONTRATO JOIN PESSOAS p ON c.IDPESSOA = p.IDPESSOA"
    params, where, joins = build_where_and_params(empresas, situacoes, table_alias_map={'conta': 'v', 'contrato': 'c'})
    where.append("v.DATA_CANCELAMENTO IS NULL")
    where.append("EXTRACT(YEAR FROM v.DATA_VENDA) = ?"); params.append(year)
    if month != 0: where.append("EXTRACT(MONTH FROM v.DATA_VENDA) = ?"); params.append(month)
    query += " " + " ".join(joins) + " WHERE " + " AND ".join(where) + " GROUP BY SETOR"
    return fetch_data_safely(conn, query, tuple(params))

# --- CORREÇÃO APLICADA AQUI ---
def get_faturamento_por_equipamento(year, month, empresas, situacoes, product_ids):
    case_clauses = " ".join([f"WHEN {cond.format(col='p.DESCRICAO_PRODUTO')} THEN '{cat}'" for cat, cond in EQUIPMENT_CATEGORIES_MAP.items()])
    group_by_expression = f"CASE {case_clauses} END"
    
    # Query base agora contém apenas as JOINs essenciais e fixas
    query = f"SELECT {group_by_expression} AS CATEGORIA, SUM(v.VALOR_VENDA) AS FATURAMENTO FROM VENDAS v JOIN CONTRATOS c ON v.IDCONTRATO = c.IDCONTRATO JOIN CONTRATOS_EQUIPAMENTO ce ON c.IDCONTRATO = ce.IDCONTRATO JOIN EQUIPAMENTOS_ITENS ei ON ce.IDEQUIPAMENTO_ITEM = ei.IDEQUIPAMENTO_ITEM JOIN PRODUTOS p ON ei.IDPRODUTO = p.IDPRODUTO"
    
    params, where, joins_from_helper = build_where_and_params(empresas, situacoes, product_ids, table_alias_map={'conta': 'v', 'contrato': 'c'})
    
    # Filtra as JOINs que já estão na query base para evitar duplicidade
    joins_to_add = [
        j for j in joins_from_helper 
        if "JOIN CONTRATOS_EQUIPAMENTO ce" not in j and "JOIN EQUIPAMENTOS_ITENS ei" not in j
    ]

    query += " " + " ".join(joins_to_add)
    
    where.append("v.DATA_CANCELAMENTO IS NULL")
    where.append("EXTRACT(YEAR FROM v.DATA_VENDA) = ?"); params.append(year)
    if month != 0: where.append("EXTRACT(MONTH FROM v.DATA_VENDA) = ?"); params.append(month)
    
    if where: query += " WHERE " + " AND ".join(where)
    
    query += f" GROUP BY {group_by_expression} HAVING {group_by_expression} IS NOT NULL"
    return fetch_data_safely(conn, query, tuple(params))


df_setor = get_faturamento_por_setor(ano_selecionado, mes_pizza, empresas_selecionadas, situacoes_selecionadas)
df_equip = get_faturamento_por_equipamento(ano_selecionado, mes_pizza, empresas_selecionadas, situacoes_selecionadas, ids_produto_selecionados)

col_pie1, col_pie2 = st.columns(2)
with col_pie1:
    if not df_setor.empty:
        fig_setor = px.pie(df_setor, names='SETOR', values='FATURAMENTO', title=f'Faturamento por Setor ({MESES_ABREV.get(mes_pizza, "Ano Inteiro")})', hole=.3)
        st.plotly_chart(fig_setor, use_container_width=True)
    else: st.warning("Não há dados de faturamento por setor para os filtros selecionados.")
with col_pie2:
    if not df_equip.empty:
        fig_equip = px.pie(df_equip, names='CATEGORIA', values='FATURAMENTO', title=f'Faturamento por Equipamento ({MESES_ABREV.get(mes_pizza, "Ano Inteiro")})', hole=.3)
        st.plotly_chart(fig_equip, use_container_width=True)
    else: st.warning("Não há dados de faturamento por equipamento para os filtros selecionados.")

st.markdown("---")

# --- Gráficos de Clientes e Equipamentos ---
def get_cumulative_clients(year, empresas, situacoes, product_ids):
    query = "SELECT c.IDPESSOA, c.DATA_INICIO FROM CONTRATOS c"
    params, where, joins = build_where_and_params(empresas, situacoes, product_ids, table_alias_map={'conta': 'c', 'contrato': 'c'})
    query += " " + " ".join(joins)
    if where: query += " WHERE " + " AND ".join(where)
    df = fetch_data_safely(conn, query, tuple(params))
    if df.empty: return pd.DataFrame({'MES': range(1, 13), 'TOTAL': [0]*12})
    df['DATA_INICIO'] = pd.to_datetime(df['DATA_INICIO'])
    start_of_year = pd.to_datetime(f'{year}-01-01')
    base_count = df[df['DATA_INICIO'] < start_of_year]['IDPESSOA'].nunique()
    monthly_totals = []
    for month in range(1, 13):
        end_of_month = pd.to_datetime(f'{year}-{month}-01') + MonthEnd(0)
        new_in_year = df[(df['DATA_INICIO'] >= start_of_year) & (df['DATA_INICIO'] <= end_of_month)]
        total_at_month_end = base_count + new_in_year['IDPESSOA'].nunique()
        monthly_totals.append(total_at_month_end)
    return pd.DataFrame({'MES': range(1, 13), 'TOTAL': monthly_totals})

def get_historical_equipment(year, empresas, situacoes, product_ids):
    query = "SELECT ce.IDCONTRATO_EQUIPAMENTO, c.DATA_INICIO, ce.DATA_RETIRADA FROM CONTRATOS_EQUIPAMENTO ce JOIN CONTRATOS c ON ce.IDCONTRATO = c.IDCONTRATO"
    params, where, joins_from_helper = build_where_and_params(empresas, situacoes, product_ids, table_alias_map={'conta': 'c', 'contrato': 'c'})
    joins_to_add = [j for j in joins_from_helper if "JOIN CONTRATOS_EQUIPAMENTO ce" not in j]
    query += " " + " ".join(joins_to_add)
    if where: query += " WHERE " + " AND ".join(where)
    df = fetch_data_safely(conn, query, tuple(params))
    if df.empty: return pd.DataFrame({'MES': range(1, 13), 'TOTAL': [0]*12})
    df['DATA_INICIO'] = pd.to_datetime(df['DATA_INICIO'])
    df['DATA_RETIRADA'] = pd.to_datetime(df['DATA_RETIRADA'], errors='coerce')
    monthly_totals = []
    for month in range(1, 13):
        end_of_month = pd.to_datetime(f'{year}-{month}-01') + MonthEnd(0)
        active_df = df[(df['DATA_INICIO'] <= end_of_month) & ((df['DATA_RETIRADA'].isnull()) | (df['DATA_RETIRADA'] > end_of_month))]
        count = active_df['IDCONTRATO_EQUIPAMENTO'].nunique()
        monthly_totals.append(count)
    return pd.DataFrame({'MES': range(1, 13), 'TOTAL': monthly_totals})

def get_cumulative_contracts(year, empresas, situacoes, product_ids):
    query = "SELECT c.IDCONTRATO, c.DATA_INICIO FROM CONTRATOS c"
    params, where, joins = build_where_and_params(
        empresas, situacoes, product_ids,
        table_alias_map={'conta': 'c', 'contrato': 'c'}
    )
    query += " " + " ".join(joins)
    if where:
        query += " WHERE " + " AND ".join(where)

    df = fetch_data_safely(conn, query, tuple(params))
    if df.empty:
        return pd.DataFrame({'MES': range(1, 13), 'TOTAL': [0] * 12})

    df['DATA_INICIO'] = pd.to_datetime(df['DATA_INICIO'])

    start_of_year = pd.to_datetime(f'{year}-01-01')

    # contratos anteriores ao início do ano
    base_count = len(df[df['DATA_INICIO'] < start_of_year])

    monthly_totals = []
    for month in range(1, 13):
        end_of_month = pd.to_datetime(f'{year}-{month}-01') + MonthEnd(0)
        # novos contratos iniciados até o fim do mês
        new_in_year = df[(df['DATA_INICIO'] >= start_of_year) & (df['DATA_INICIO'] <= end_of_month)]
        total_at_month_end = base_count + len(new_in_year)
        monthly_totals.append(total_at_month_end)

    return pd.DataFrame({'MES': range(1, 13), 'TOTAL': monthly_totals})

def plot_cumulative_chart(df_atual, df_anterior, title, yaxis_title):
    df_merged = pd.merge(df_atual.rename(columns={'TOTAL': 'ATUAL'}), df_anterior.rename(columns={'TOTAL': 'ANTERIOR'}), on='MES')
    df_merged['MES_ABREV'] = df_merged['MES'].map(MESES_ABREV)
    fig = go.Figure()
    fig.add_trace(go.Bar(name=f'{ano_selecionado - 1}', x=df_merged['MES_ABREV'], y=df_merged['ANTERIOR'], marker_color='lightslategray', text=df_merged['ANTERIOR'], textposition='outside'))
    if ano_selecionado == ano_atual:
        df_real = df_merged[df_merged['MES'] <= meses_fechados] if meses_fechados > 0 else df_merged[df_merged['MES'] <= data_hoje.month]
        crescimento_medio = (df_real['ATUAL'].iloc[-1] - df_real['ATUAL'].iloc[0]) / (len(df_real) - 1) if len(df_real) > 1 else (df_real['ATUAL'].iloc[0] if not df_real.empty else 0)
        valores_tendencia = list(df_merged['ATUAL'])
        if not df_real.empty:
            ultimo_valor_real = df_real['ATUAL'].iloc[-1]
            for i in range(meses_fechados, 12):
                ultimo_valor_real += crescimento_medio
                valores_tendencia[i] = ultimo_valor_real
        colors = ['cornflowerblue'] * meses_fechados + ['lightskyblue'] * (12 - meses_fechados)
        fig.add_trace(go.Bar(name=f'{ano_selecionado}', x=df_merged['MES_ABREV'], y=valores_tendencia, marker_color=colors, text=[f'{int(v):,}' for v in valores_tendencia], textposition='outside'))
    else:
        fig.add_trace(go.Bar(name=f'{ano_selecionado}', x=df_merged['MES_ABREV'], y=df_merged['ATUAL'], marker_color='cornflowerblue', text=df_merged['ATUAL'], textposition='outside'))
    fig.update_layout(barmode='group', title=title, xaxis_title='Mês', yaxis_title=yaxis_title)
    st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False})
    if ano_selecionado == ano_atual:
        st.info("As barras mais claras representam uma tendência baseada no crescimento médio dos meses passados.")

st.subheader("Total de Clientes Ativos")
df_cli_atual = get_cumulative_clients(ano_selecionado, empresas_selecionadas, situacoes_selecionadas, ids_produto_selecionados)
df_cli_anterior = get_cumulative_clients(ano_selecionado - 1, empresas_selecionadas, situacoes_selecionadas, ids_produto_selecionados)
plot_cumulative_chart(df_cli_atual, df_cli_anterior, "Total de Clientes Ativos ao Final de Cada Mês", "Total de Clientes")

st.subheader("Total de Equipamentos Ativos")
df_equip_atual = get_historical_equipment(ano_selecionado, empresas_selecionadas, situacoes_selecionadas, ids_produto_selecionados)
df_equip_anterior = get_historical_equipment(ano_selecionado - 1, empresas_selecionadas, situacoes_selecionadas, ids_produto_selecionados)
plot_cumulative_chart(df_equip_atual, df_equip_anterior, "Total de Equipamentos Ativos ao Final de Cada Mês", "Total de Equipamentos")

st.subheader("Total de Contratos Ativos")
df_contr_atual = get_cumulative_contracts(ano_selecionado, empresas_selecionadas, situacoes_selecionadas, ids_produto_selecionados)
df_contr_anterior = get_cumulative_contracts(ano_selecionado - 1, empresas_selecionadas, situacoes_selecionadas, ids_produto_selecionados)
plot_cumulative_chart(df_contr_atual, df_contr_anterior, "Total de Contratos Ativos ao Final de Cada Mês", "Total de Contratos")

# --- Botão de Exportação ---
st.header("Exportar Dados")
if st.button("Gerar Relatório em Excel"):
    with st.spinner("Preparando arquivo..."):
        df_cli_merged = pd.merge(df_cli_atual.rename(columns={'TOTAL': f'CLIENTES_{ano_selecionado}'}), df_cli_anterior.rename(columns={'TOTAL': f'CLIENTES_{ano_selecionado-1}'}), on='MES')
        df_equip_merged = pd.merge(df_equip_atual.rename(columns={'TOTAL': f'EQUIP_{ano_selecionado}'}), df_equip_anterior.rename(columns={'TOTAL': f'EQUIP_{ano_selecionado-1}'}), on='MES')
        dataframes_to_export = {
            "Faturamento_Mensal": df_fat_mensal,
            "Faturamento_por_Setor": df_setor,
            "Faturamento_por_Equipamento": df_equip,
            "Clientes_Ativos_Mensal": df_cli_merged,
            "Equipamentos_Ativos_Mensal": df_equip_merged,
        }
        excel_data = to_excel(dataframes_to_export)
        st.download_button(
            label="Clique aqui para baixar o Excel",
            data=excel_data,
            file_name=f"relatorio_geral_{ano_selecionado}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )