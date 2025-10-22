import streamlit as st
import pandas as pd
from firebird.driver import connect, driver_config

@st.cache_resource(ttl=600)
def get_connection():
    """Estabelece e retorna uma conexão com o banco de dados Firebird."""
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
def fetch_data(_conn, query, params=None):
    """
    Executa uma query no banco de dados e retorna o resultado como um DataFrame do Pandas.
    O _conn é um argumento "dummy" para garantir que o cache seja invalidado se a conexão mudar.
    """
    if _conn is None:
        return pd.DataFrame()
    try:
        df = pd.read_sql(query, _conn, params=params)
        return df
    except Exception as e:
        st.error(f"Erro ao executar a query: {e}")
        st.code(query, language="sql")
        return pd.DataFrame()