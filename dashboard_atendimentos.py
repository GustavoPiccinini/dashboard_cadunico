import io
import os
import tempfile
import streamlit as st
import duckdb
import pandas as pd
import plotly.express as px


st.set_page_config(page_title="Dashboard de Atendimentos", page_icon="📋", layout="wide")

st.markdown("""
<style>
    div[data-testid="metric-container"] { background:#f0f2f6; border-radius:10px; padding:12px; }
    .block-container { padding-top:1.5rem; }
</style>
""", unsafe_allow_html=True)

# ══════════════════════════════════════════════
# MAPEAMENTO DE COLUNAS
# ══════════════════════════════════════════════
COL = {
    "codigo":     "Codigo_do_grupo",
    "cpf":        "CPF",
    "nis":        "NIS",
    "nascimento": "DATA_DE_NASCIMENTO",
    "nome":       "Nome_referencia",
    "data":       "DATA",
    "servico":    "SERVICO",
    "quantia":    "QUANTIA",
    "unidade":    "UNIDADE_DE_ATENDIMENTO",
    "login":      "login",
    "categoria":  "Categoria",
}

# Colunas do CadÚnico que vamos efetivamente usar (de ~190 colunas no arquivo original)
CADUNICO_COLS = {
    "cpf":        "p.num_cpf_pessoa",
    "rg":         "p.num_identidade_pessoa",
    "nis":        "p.num_nis_pessoa_atual",
    "nome":       "p.nom_pessoa",
    "nascimento": "p.dta_nasc_pessoa",
    "ref_cad":    "d.ref_cad",
    "marc_pbf":   "d.marc_pbf",
}

# ══════════════════════════════════════════════
# CONEXÃO DUCKDB — reconecta automaticamente em reruns
# ══════════════════════════════════════════════
def criar_conexao(filepath: str) -> duckdb.DuckDBPyConnection:
    # Converte qualquer arquivo para CSV UTF-8 limpo via pandas
    ext = os.path.splitext(filepath)[1].lower()
    csv_path = filepath + "_clean.csv"
    parquet_path = filepath + ".parquet"

    if not os.path.exists(csv_path):
        df_tmp = None

        if ext == ".csv":
            for enc in ["utf-8", "latin-1", "cp1252", "iso-8859-1"]:
                for sep in [",", ";", "\t"]:
                    try:
                        df_tmp = pd.read_csv(filepath, encoding=enc, sep=sep, engine="python")
                        if df_tmp.shape[1] > 1:
                            break
                    except Exception:
                        continue
                if df_tmp is not None and df_tmp.shape[1] > 1:
                    break

        elif ext in [".xlsx", ".xls"]:
            df_tmp = pd.read_excel(filepath)

        elif ext == ".parquet":
            df_tmp = pd.read_parquet(filepath)

        else:
            raise ValueError(f"Formato de arquivo não suportado: {ext}")

        # validação
        if df_tmp is None or df_tmp.shape[1] <= 1:
            raise ValueError("Não foi possível ler o arquivo.")

        # Corrigir coluna DATA
        col_data = next((c for c in df_tmp.columns if c.strip().upper() == "DATA"), None)
        if col_data:
            df_tmp[col_data] = pd.to_datetime(
                df_tmp[col_data].astype(str).str.strip(),
                dayfirst=True,
                errors="coerce"
            ).dt.strftime("%Y-%m-%d %H:%M:%S")

        # salvar CSV e Parquet
        df_tmp.to_csv(csv_path, index=False, encoding="utf-8")
        df_tmp.to_parquet(parquet_path, index=False)

        # salvar caminhos
        st.session_state["tmp_csv"] = csv_path
        st.session_state["tmp_parquet"] = parquet_path

        del df_tmp

    con = duckdb.connect()

    parquet_path = st.session_state.get("tmp_parquet")

    if parquet_path and os.path.exists(parquet_path):
        con.execute(f"""
            CREATE OR REPLACE VIEW dados AS
            SELECT * FROM '{parquet_path}'
        """)
    else:
        con.execute(f"""
            CREATE OR REPLACE VIEW dados AS
            SELECT * FROM read_csv_auto('{csv_path}',
                header=true,
                delim=',',
                ignore_errors=true,
                auto_detect=true
            )
        """)

    con.execute("SELECT COUNT(*) FROM dados").fetchone()
    return con


def get_con() -> duckdb.DuckDBPyConnection:
    """Retorna conexão válida, recriando se necessário."""
    tmp_path = st.session_state.get("tmp_path")
    if not tmp_path:
        st.error("Faça upload do arquivo.")
        st.stop()
    con = st.session_state.get("con")
    try:
        if con:
            con.execute("SELECT 1").fetchone()  # health check leve
            return con
    except Exception:
        pass
    con = criar_conexao(tmp_path)
    st.session_state["con"] = con
    return con


def run(sql: str) -> pd.DataFrame:
    return get_con().execute(sql).df()


def run_val(sql: str):
    return get_con().execute(sql).fetchone()[0]


@st.cache_data(ttl=3600, show_spinner=False)
def get_colunas(_cache_key: str) -> list:
    """Retorna lista de colunas disponíveis — executa só uma vez por arquivo."""
    try:
        df_cols = get_con().execute("SELECT * FROM dados LIMIT 0").df()
        return list(df_cols.columns)
    except Exception:
        return []

def safe_col(key: str):
    cache_key = st.session_state.get("last_file", "")
    colunas = get_colunas(cache_key)
    c = COL.get(key, key)
    return c if c in colunas else None

# ══════════════════════════════════════════════
# UPLOAD
# ══════════════════════════════════════════════
st.sidebar.markdown("---")
st.sidebar.title("⚙️ Configurações")
st.sidebar.markdown("---")

uploaded = st.sidebar.file_uploader(
    "📂 Carregar arquivo", type=["csv", "xlsx", "xls","parquet"],
    help="CSV ou Excel. Processado via DuckDB."
)

if uploaded:
    if st.session_state.get("last_file") != uploaded.name:
        suffix = os.path.splitext(uploaded.name)[1]
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        tmp.write(uploaded.read())
        tmp.flush()
        tmp.close()
        st.session_state["tmp_path"] = tmp.name
        st.session_state["last_file"] = uploaded.name
        st.session_state.pop("con", None)  # força reconexão
    try:
        total_geral = run_val("SELECT COUNT(*) FROM dados")
        st.session_state["total_geral"] = total_geral
        st.sidebar.success(f"✅ {total_geral:,} registros carregados!")
    except Exception as e:
        st.sidebar.error(f"Erro: {e}")
        st.stop()
else:
    st.sidebar.info("💡 Faça upload do arquivo para começar.")
    st.title("📋 Dashboard de Atendimentos")
    st.info("📂 Faça upload do seu arquivo CSV ou Excel na barra lateral.")
    st.stop()

# ══════════════════════════════════════════════
# COLUNAS DISPONÍVEIS
# ══════════════════════════════════════════════
c_cpf      = safe_col("cpf")
c_nome     = safe_col("nome")
c_unidade  = safe_col("unidade")
c_servico  = safe_col("servico")
c_categoria= safe_col("categoria")
c_login    = safe_col("login")
c_data     = safe_col("data")
c_nis      = safe_col("nis")
c_nasc     = safe_col("nascimento")
c_codigo   = safe_col("codigo")
c_quantia  = safe_col("quantia")

# ══════════════════════════════════════════════
# UPLOAD — CADÚNICO (múltiplos meses)
# ══════════════════════════════════════════════
st.sidebar.markdown("---")
st.sidebar.title("📑 CadÚnico (opcional)")
st.sidebar.caption("Carregue 1 arquivo por mês — apenas as colunas relevantes são mantidas em memória.")

cadunico_files = st.sidebar.file_uploader(
    "📂 Carregar planilhas do CadÚnico", type=["csv", "xlsx", "xls"],
    accept_multiple_files=True,
    help="Cada arquivo é processado e convertido em Parquet (colunas selecionadas), evitando uso excessivo de memória.",
    key="cadunico_uploader"
)

CADUNICO_DIR = os.path.join(tempfile.gettempdir(), "cadunico_parquet")
os.makedirs(CADUNICO_DIR, exist_ok=True)

def _normalize_colname(c):
    return str(c).strip().lower().replace(" ", "").split(".")[-1]

def _normalize_colname_keep_prefix(c):
    return str(c).strip().lower().replace(" ", "")

def _find_col(df_cols, target_lower):
    """Encontra coluna no df, priorizando match exato com prefixo; cai para match sem prefixo se necessário."""
    target_exact = _normalize_colname_keep_prefix(target_lower)
    target_clean = _normalize_colname(target_lower)
    # 1ª tentativa: match exato incluindo prefixo (d. ou p.)
    for c in df_cols:
        if _normalize_colname_keep_prefix(c) == target_exact:
            return c
    # 2ª tentativa: match ignorando prefixo
    for c in df_cols:
        if _normalize_colname(c) == target_clean:
            return c
    return None

def processar_arquivo_cadunico(uploaded_file) -> str:
    """Lê 1 arquivo do CadÚnico, extrai só as colunas relevantes, salva como Parquet. Retorna o caminho."""
    out_path = os.path.join(CADUNICO_DIR, f"{uploaded_file.name}.parquet")
    if os.path.exists(out_path):
        return out_path

    suffix = os.path.splitext(uploaded_file.name)[1].lower()
    if suffix == ".csv":
        uploaded_file.seek(0)
        raw_bytes = uploaded_file.read()
        raw_text = None
        for encoding in ["utf-8-sig", "utf-8", "latin1", "cp1252"]:
            try:
                raw_text = raw_bytes.decode(encoding)
                break
            except Exception:
                continue
        if raw_text is None:
            raise ValueError(f"Não consegui decodificar {uploaded_file.name}.")

        linhas = raw_text.splitlines()
        alvo_norm = set(_normalize_colname(v) for v in CADUNICO_COLS.values())

        # Para cada separador candidato, encontra a primeira linha (nas primeiras 30)
        # cujos campos batem com pelo menos 2 colunas-alvo conhecidas — essa é a linha de cabeçalho real.
        candidatos_sep = ["\t", ";", ",", "|"]
        melhor_sep, melhor_header_idx, melhor_hits = None, None, 0
        for sep in candidatos_sep:
            for idx, linha in enumerate(linhas[:30]):
                campos_norm = [_normalize_colname(x) for x in linha.split(sep)]
                hits = sum(1 for c in campos_norm if c in alvo_norm)
                if hits > melhor_hits:
                    melhor_hits = hits
                    melhor_sep = sep
                    melhor_header_idx = idx

        if melhor_sep is None:
            raise ValueError(
                f"Não consegui identificar a linha de cabeçalho em {uploaded_file.name}. "
                f"Verifique se o arquivo contém as colunas esperadas (ex: p.num_cpf_pessoa)."
            )

        import io as _io
        df_raw = pd.read_csv(
            _io.StringIO(raw_text), dtype=str,
            sep=melhor_sep, skiprows=melhor_header_idx, engine="python",
            on_bad_lines="skip"
        )
    else:
        df_raw = pd.read_excel(uploaded_file, dtype=str)

    df_raw.columns = [str(c).strip() for c in df_raw.columns]

    col_map = {}
    for key, target in CADUNICO_COLS.items():
        found = _find_col(df_raw.columns, target)
        if found:
            col_map[key] = found

    if "cpf" not in col_map and "nis" not in col_map:
        preview = ", ".join(str(c) for c in df_raw.columns[:15])
        raise ValueError(
            f"Não encontrei colunas de CPF nem NIS em {uploaded_file.name} "
            f"({df_raw.shape[1]} colunas detectadas). Primeiras colunas lidas: {preview}"
        )

    cols_existentes = list(col_map.values())
    df_slim = df_raw[cols_existentes].copy()
    df_slim.columns = list(col_map.keys())

    # Normaliza CPF/NIS/RG (remove .0, espaços)
    for c in ["cpf", "nis", "rg"]:
        if c in df_slim.columns:
            df_slim[c] = (
                df_slim[c].astype(str)
                .str.replace(r"\.0$", "", regex=True)
                .str.strip()
                .replace({"nan": None, "None": None, "": None})
            )

    # ref_cad para competência mensal — se ausente, usa nome do arquivo
    if "ref_cad" not in df_slim.columns:
        df_slim["ref_cad"] = os.path.splitext(uploaded_file.name)[0]

    df_slim["arquivo_origem"] = uploaded_file.name
    df_slim.to_parquet(out_path, index=False)
    del df_raw, df_slim
    return out_path


cadunico_loaded = False
if cadunico_files:
    paths_cadunico = []
    erros_cadunico = []
    for f in cadunico_files:
        try:
            p = processar_arquivo_cadunico(f)
            paths_cadunico.append(p)
        except Exception as e:
            erros_cadunico.append(f"{f.name}: {e}")

    if erros_cadunico:
        for e in erros_cadunico:
            st.sidebar.error(f"❌ {e}")

    if paths_cadunico:
        try:
            con_cad = get_con()
            glob_pattern = os.path.join(CADUNICO_DIR, "*.parquet")
            con_cad.execute(f"""
                CREATE OR REPLACE VIEW cadunico AS
                SELECT * FROM read_parquet('{glob_pattern}', union_by_name=true)
            """)
            total_cad = con_cad.execute("SELECT COUNT(*) FROM cadunico").fetchone()[0]
            meses_cad = con_cad.execute("SELECT COUNT(DISTINCT ref_cad) FROM cadunico").fetchone()[0]
            st.sidebar.success(f"✅ CadÚnico: {total_cad:,} registros em {meses_cad} competência(s)")
            cadunico_loaded = True
        except Exception as e:
            st.sidebar.error(f"Erro ao consolidar CadÚnico: {e}")
else:
    st.sidebar.caption("Nenhum arquivo do CadÚnico carregado ainda.")

def esc(v: str) -> str:
    """Escapa aspas simples para uso seguro em SQL."""
    return str(v).replace("'", "''")

def altura_grafico(n_itens: int, min_h: int = 200, por_item: int = 40) -> int:
    """Calcula altura proporcional ao número de itens."""
    return max(min_h, min(n_itens * por_item + 80, 600))

@st.cache_data(ttl=300, show_spinner=False)
def opts_db_cached(col, label_all, _cache_key):
    if not col:
        return [label_all]
    try:
        con = get_con()
        vals = con.execute(f'SELECT DISTINCT "{col}" FROM dados WHERE "{col}" IS NOT NULL ORDER BY "{col}" LIMIT 500').df()[col].tolist()
        return [label_all] + [str(v) for v in vals]
    except Exception:
        return [label_all]

def opts_db(col, label_all):
    cache_key = st.session_state.get("last_file", "")
    return opts_db_cached(col, label_all, cache_key)

# ══════════════════════════════════════════════
# FILTROS
# ══════════════════════════════════════════════
st.sidebar.markdown("### 🔍 Filtros")
search      = st.sidebar.text_input("Buscar por nome ou CPF", placeholder="Digite aqui...")
f_unidade   = st.sidebar.selectbox("Unidade",   opts_db(c_unidade,  "Todas"))
f_servico   = st.sidebar.selectbox("Serviço",   opts_db(c_servico,  "Todos"))
f_categoria = st.sidebar.selectbox("Categoria", opts_db(c_categoria,"Todas"))
f_login     = st.sidebar.selectbox("Atendente", opts_db(c_login,    "Todos"))

f_data = None
if c_data:
    try:
        dmin = run(f'SELECT MIN(CAST("{c_data}" AS DATE)) FROM dados').iloc[0, 0]
        dmax = run(f'SELECT MAX(CAST("{c_data}" AS DATE)) FROM dados').iloc[0, 0]
        if dmin and dmax:
            import datetime
            dmin_dt = dmin if isinstance(dmin, datetime.date) else pd.to_datetime(dmin).date()
            dmax_dt = dmax if isinstance(dmax, datetime.date) else pd.to_datetime(dmax).date()
            f_data = st.sidebar.date_input(
                "Período",
                value=(dmin_dt, dmax_dt),
                min_value=dmin_dt,
                max_value=dmax_dt,
            )
            st.sidebar.caption(f"📅 Arquivo: {dmin_dt.strftime('%d/%m/%Y')} → {dmax_dt.strftime('%d/%m/%Y')}")
    except Exception:
        pass

# ══════════════════════════════════════════════
# WHERE CLAUSE
# ══════════════════════════════════════════════
wheres = []
if search:
    parts = []
    if c_nome: parts.append(f"LOWER(CAST(\"{c_nome}\" AS VARCHAR)) LIKE '%{search.lower()}%'")
    if c_cpf:  parts.append(f"CAST(\"{c_cpf}\" AS VARCHAR) LIKE '%{search}%'")
    if parts:  wheres.append(f"({' OR '.join(parts)})")
if f_unidade   != "Todas" and c_unidade:   wheres.append(f'"{c_unidade}" = \'{esc(f_unidade)}\'')
if f_servico   != "Todos" and c_servico:   wheres.append(f'"{c_servico}" = \'{esc(f_servico)}\'')
if f_categoria != "Todas" and c_categoria: wheres.append(f'"{c_categoria}" = \'{esc(f_categoria)}\'')
if f_login     != "Todos" and c_login:     wheres.append(f'"{c_login}" = \'{esc(f_login)}\'')
if f_data and len(f_data) == 2 and c_data:
    wheres.append(f"CAST(\"{c_data}\" AS DATE) BETWEEN '{f_data[0]}' AND '{f_data[1]}'")

where_sql = ("WHERE " + " AND ".join(wheres)) if wheres else ""

# ══════════════════════════════════════════════
# MÉTRICAS
# ══════════════════════════════════════════════
st.title("📋 Dashboard de Atendimentos")
st.caption("Clique em qualquer linha para ver o perfil completo.")
st.markdown("---")

@st.cache_data(ttl=120, show_spinner=False)
def calc_metricas(where: str, _ck: str):
    """Calcula todas as métricas de uma vez — cache de 2 min."""
    con = get_con()
    def qv(sql):
        try: return con.execute(sql).fetchone()[0]
        except: return 0
    tf   = qv(f"SELECT COUNT(*) FROM dados {where}")
    cf   = qv(f'SELECT COUNT(DISTINCT "{c_cpf}") FROM dados {where}')     if c_cpf     else 0
    uf   = qv(f'SELECT COUNT(DISTINCT "{c_unidade}") FROM dados {where}') if c_unidade else 0
    sf   = qv(f'SELECT COUNT(DISTINCT "{c_servico}") FROM dados {where}') if c_servico else 0
    lf   = qv(f'SELECT COUNT(DISTINCT "{c_login}") FROM dados {where}')   if c_login   else 0
    taxa = 0
    if c_cpf and cf > 0:
        multi = qv(f'SELECT COUNT(*) FROM (SELECT "{c_cpf}" FROM dados {where} GROUP BY "{c_cpf}" HAVING COUNT(*) > 1)')
        taxa = round(multi / cf * 100, 1)
    delta = ""
    if c_data:
        ao = "AND" if where else "WHERE"
        ma = qv(f'SELECT COUNT(*) FROM dados {where} {ao} CAST("{c_data}" AS DATE) >= DATE_TRUNC(\'month\', CURRENT_DATE)')
        mp = qv(f'SELECT COUNT(*) FROM dados {where} {ao} CAST("{c_data}" AS DATE) >= DATE_TRUNC(\'month\', CURRENT_DATE) - INTERVAL 1 MONTH AND CAST("{c_data}" AS DATE) < DATE_TRUNC(\'month\', CURRENT_DATE)')
        if mp > 0:
            delta = f"{round(((ma-mp)/mp)*100,1):+.1f}% vs mês anterior"
    return tf, cf, uf, sf, lf, taxa, delta

_ck = st.session_state.get("last_file", "")
total_f, cpfs_f, uni_f, svc_f, login_f, taxa_retorno, delta_txt = calc_metricas(where_sql, _ck)

m1, m2, m3, m4, m5, m6 = st.columns(6)
m1.metric("Total atendimentos", f"{total_f:,}", delta_txt if delta_txt else None)
m2.metric("CPFs distintos",     f"{cpfs_f:,}")
m3.metric("Unidades ativas",    f"{uni_f:,}")
m4.metric("Tipos de serviço",   f"{svc_f:,}")
m5.metric("Atendentes ativos",  f"{login_f:,}")
m6.metric("Taxa de retorno",    f"{taxa_retorno}%", help="CPFs com mais de 1 atendimento")
st.markdown("---")

# ══════════════════════════════════════════════
# ABAS
# ══════════════════════════════════════════════
aba_reg, aba_graf, aba_at, aba_alertas, aba_recorr, aba_cad, aba_exp = st.tabs(["📄 Individuos", "📊 Gráficos", "👥 Atendentes", "🚨 Alertas", "🔄 Recorrência Alternada", "🔗 CadÚnico", "📥 Exportar"])


# ─────────────────────────────────────
# ABA 1 — Individuos
# ─────────────────────────────────────
with aba_reg:
    st.subheader("Registros de atendimento")
    cols_tab = [c for c in [c_codigo, c_nome, c_cpf, c_unidade, c_servico, c_data, c_login, c_categoria] if c]
    cols_sel = ", ".join([f'"{c}"' for c in cols_tab])

    PAGE_SIZE = 100
    total_pages = max(1, (total_f + PAGE_SIZE - 1) // PAGE_SIZE)
    pg_col, _ = st.columns([1, 3])
    with pg_col:
        page = st.number_input("Página", min_value=1, max_value=total_pages, value=1, step=1)
    offset = (page - 1) * PAGE_SIZE
    st.caption(f"Página {page} de {total_pages} — {total_f:,} registros no total")

    df_tab = run(f"SELECT {cols_sel} FROM dados {where_sql} LIMIT {PAGE_SIZE} OFFSET {offset}")

    evento = st.dataframe(df_tab, use_container_width=True, hide_index=True,
                          on_select="rerun", selection_mode="single-row")

    sel = evento.selection.rows if hasattr(evento, "selection") else []
    if sel and c_cpf:
        row = df_tab.iloc[sel[0]]
        cpf_sel = str(row.get(c_cpf, "")).replace("'", "''")
        if cpf_sel:
            st.markdown("---")
            st.subheader(f"👤 Perfil: {row.get(c_nome, 'Cidadão')}")
            total_cpf = run_val("SELECT COUNT(*) FROM dados WHERE " + chr(34) + c_cpf + chr(34) + " = '" + cpf_sel + "'")
            pa, pb, pc, pd_ = st.columns(4)
            pa.metric("CPF",           cpf_sel)
            pb.metric("NIS",           str(row.get(c_nis,  "—")))
            pc.metric("Nascimento",    str(row.get(c_nasc, "—")))
            pd_.metric("Atendimentos", total_cpf)

            cols_h = [c for c in [c_data, c_servico, c_unidade, c_quantia, c_login, c_categoria] if c]
            df_hist = run("SELECT " + ", ".join([chr(34)+c+chr(34) for c in cols_h]) + " FROM dados WHERE " + chr(34) + c_cpf + chr(34) + " = '" + cpf_sel + "' LIMIT 500") 
            if len(df_hist) == 500:
                st.caption(f"⚠️ Exibindo 500 de {total_cpf:,} atendimentos para este CPF.")    
            st.markdown("##### Histórico de serviços")
            st.dataframe(df_hist, use_container_width=True, hide_index=True)

            if c_servico:
                svc_c = run("SELECT " + chr(34) + c_servico + chr(34) + " AS Servico, COUNT(*) AS Qtd FROM dados WHERE " + chr(34) + c_cpf + chr(34) + " = '" + cpf_sel + "' GROUP BY " + chr(34) + c_servico + chr(34) + " ORDER BY Qtd DESC")
                fig = px.bar(svc_c, x="Qtd", y="Servico", orientation="h",
                             title="Serviços recebidos", color="Qtd",
                             color_continuous_scale="Blues", text="Qtd")
                fig.update_layout(coloraxis_showscale=False, yaxis_title=None, xaxis_title="Quantidade")
                fig.update_traces(textposition="outside")
                st.plotly_chart(fig, use_container_width=True)

# ─────────────────────────────────────
# ABA 2 — GRÁFICOS
# ─────────────────────────────────────
with aba_graf:
    if total_f == 0:
        st.warning("Nenhum dado com os filtros atuais.")
    else:
        g1, g2 = st.columns(2)
        with g1:
            if c_servico:
                d = run(f'SELECT "{c_servico}" AS Servico, COUNT(*) AS Qtd FROM dados {where_sql} GROUP BY "{c_servico}" ORDER BY Qtd DESC LIMIT 10')
                fig1 = px.bar(d, x="Qtd", y="Servico", orientation="h", title="Por tipo de serviço",
                              color="Qtd", color_continuous_scale="Teal", text="Qtd",
                              height=altura_grafico(len(d)))
                fig1.update_layout(coloraxis_showscale=False, yaxis_title=None, xaxis_title="Quantidade")
                fig1.update_traces(textposition="outside")
                st.plotly_chart(fig1, use_container_width=True)
        with g2:
            if c_unidade:
                d = run(f'SELECT "{c_unidade}" AS Unidade, COUNT(*) AS Qtd FROM dados {where_sql} GROUP BY "{c_unidade}" ORDER BY Qtd DESC')
                fig2 = px.bar(d, x="Qtd", y="Unidade", orientation="h", title="Por unidade",
                              color="Qtd", color_continuous_scale="Purples", text="Qtd",
                              height=altura_grafico(len(d)))
                fig2.update_layout(coloraxis_showscale=False, yaxis_title=None, xaxis_title="Quantidade")
                fig2.update_traces(textposition="outside")
                st.plotly_chart(fig2, use_container_width=True)

        g3, g4 = st.columns(2)
        with g3:
            if c_login:
                try:
                    d = run(f'SELECT "{c_login}" AS Atendente, COUNT(*) AS Qtd FROM dados {where_sql} GROUP BY "{c_login}" ORDER BY Qtd DESC LIMIT 10')
                    fig3 = px.bar(d, x="Qtd", y="Atendente", orientation="h", title="Top 10 atendentes",
                                  color="Qtd", color_continuous_scale="Oranges", text="Qtd",
                                  height=altura_grafico(len(d)))
                    fig3.update_layout(coloraxis_showscale=False, yaxis_title=None, xaxis_title="Quantidade")
                    fig3.update_traces(textposition="outside")
                    st.plotly_chart(fig3, use_container_width=True)
                except Exception:
                    st.caption("Gráfico de atendentes indisponível.")
        with g4:
            if c_data:
                try:
                    w_data = f"{where_sql} AND" if where_sql.strip() else "WHERE"
                    d = run(f'''
                        SELECT STRFTIME(CAST("{c_data}" AS DATE), '%Y-%m') AS Mes, COUNT(*) AS Qtd
                        FROM dados {w_data} "{c_data}" IS NOT NULL
                        GROUP BY Mes ORDER BY Mes
                    ''')
                    if not d.empty:
                        # Destacar últimos 12 meses
                        d = d.tail(24)
                        fig4 = px.line(d, x="Mes", y="Qtd", title="Evolução mensal (últimos 24 meses)", markers=True)
                        fig4.update_layout(xaxis_title="Mês", yaxis_title="Atendimentos",
                                           xaxis_tickangle=-45)
                        fig4.update_traces(line_color="#1f77b4", line_width=2)
                        st.plotly_chart(fig4, use_container_width=True)
                except Exception:
                    st.caption("Gráfico de evolução indisponível.")

        # Ranking clicável — Serviços e CPFs
        if c_servico and c_cpf:
            st.markdown("##### 🏆 Ranking — Serviços mais procurados")
            top_svc = run(f'SELECT "{c_servico}" AS Servico, COUNT(*) AS Total, COUNT(DISTINCT "{c_cpf}") AS CPFs_unicos FROM dados {where_sql} GROUP BY "{c_servico}" ORDER BY Total DESC LIMIT 10')
            ev_svc = st.dataframe(top_svc, use_container_width=True, hide_index=True,
                                  on_select="rerun", selection_mode="single-row")
            svc_sel_rows = ev_svc.selection.rows if hasattr(ev_svc, "selection") else []
            if svc_sel_rows:
                svc_nome = top_svc.iloc[svc_sel_rows[0]]["Servico"]
                svc_safe = esc(svc_nome)
                st.markdown(f"**Registros para: {svc_nome}**")
                cols_svc = [c for c in [c_nome, c_cpf, c_unidade, c_data, c_login] if c]
                and_or = "AND" if where_sql else "WHERE"
                df_svc = run("SELECT " + ", ".join([chr(34)+c+chr(34) for c in cols_svc]) + " FROM dados " + where_sql + " " + and_or + " " + chr(34) + c_servico + chr(34) + " = '" + svc_safe + "' LIMIT 200")
                st.dataframe(df_svc, use_container_width=True, hide_index=True)

            st.markdown("##### 👤 Top 10 CPFs com mais atendimentos")
            if c_nome:
                top_cpf = run(f'SELECT "{c_nome}" AS Nome, "{c_cpf}" AS CPF, COUNT(*) AS Atendimentos FROM dados {where_sql} GROUP BY "{c_cpf}", "{c_nome}" ORDER BY Atendimentos DESC LIMIT 10')
            else:
                top_cpf = run(f'SELECT "{c_cpf}" AS CPF, COUNT(*) AS Atendimentos FROM dados {where_sql} GROUP BY "{c_cpf}" ORDER BY Atendimentos DESC LIMIT 10')
            ev_cpf = st.dataframe(top_cpf, use_container_width=True, hide_index=True,
                                  on_select="rerun", selection_mode="single-row")
            cpf_sel_rows = ev_cpf.selection.rows if hasattr(ev_cpf, "selection") else []
            if cpf_sel_rows:
                cpf_click = top_cpf.iloc[cpf_sel_rows[0]]["CPF"]
                cpf_safe = esc(str(cpf_click))
                nome_click = top_cpf.iloc[cpf_sel_rows[0]].get("Nome", cpf_click)
                total_click = run_val("SELECT COUNT(*) FROM dados WHERE " + chr(34) + c_cpf + chr(34) + " = '" + cpf_safe + "'")
                st.markdown(f"**Histórico: {nome_click} — {total_click:,} atendimentos**")
                cols_h = [c for c in [c_data, c_servico, c_unidade, c_login, c_categoria] if c]
                df_click = run("SELECT " + ", ".join([chr(34)+c+chr(34) for c in cols_h]) + " FROM dados WHERE " + chr(34) + c_cpf + chr(34) + " = '" + cpf_safe + "' ORDER BY " + chr(34) + str(c_data or "") + chr(34) + " DESC LIMIT 200")
                st.dataframe(df_click, use_container_width=True, hide_index=True)

# ─────────────────────────────────────
# ABA 3 — ATENDENTES E UNIDADES
# ─────────────────────────────────────
with aba_at:
    st.subheader("Perfil por atendente e unidade")
    w_base = f"{where_sql} AND" if where_sql.strip() else "WHERE"

    col_fat, col_funi = st.columns(2)
    with col_fat:
        if c_login:
            atendentes = run(f'SELECT DISTINCT "{c_login}" FROM dados {w_base} "{c_login}" IS NOT NULL ORDER BY "{c_login}"')[c_login].tolist()
            at_sels = st.multiselect("Selecione atendentes", atendentes)
        else:
            at_sels = []
    with col_funi:
        if c_unidade:
            unidades_at = run(f'SELECT DISTINCT "{c_unidade}" FROM dados {w_base} "{c_unidade}" IS NOT NULL ORDER BY "{c_unidade}"')[c_unidade].tolist()
            uni_sels = st.multiselect("Selecione unidades", unidades_at)
        else:
            uni_sels = []

    # Monta WHERE combinado
    if at_sels or uni_sels:
        wheres_at = []
        if at_sels and c_login:
            at_lista = ", ".join(["'" + esc(a) + "'" for a in at_sels])
            wheres_at.append(f'"{c_login}" IN ({at_lista})')
        if uni_sels and c_unidade:
            uni_lista = ", ".join(["'" + esc(u) + "'" for u in uni_sels])
            wheres_at.append(f'"{c_unidade}" IN ({uni_lista})')
        w_at = "WHERE " + " AND ".join(wheres_at)

        # ── Métricas ──
        tot_at  = run_val(f"SELECT COUNT(*) FROM dados {w_at}")
        q_cpf   = f'SELECT COUNT(DISTINCT "{c_cpf}") FROM dados {w_at}'
        q_uni   = f'SELECT COUNT(DISTINCT "{c_unidade}") FROM dados {w_at}'
        q_svc   = f'SELECT COUNT(DISTINCT "{c_servico}") FROM dados {w_at}'
        cpf_at  = run_val(q_cpf)  if c_cpf     else None
        uni_cnt = run_val(q_uni)  if c_unidade else None
        svc_cnt = run_val(q_svc)  if c_servico else None

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Total atendimentos", f"{tot_at:,}")
        m2.metric("CPFs atendidos",     f"{cpf_at:,}"  if cpf_at  is not None else "—")
        m3.metric("Unidades",           f"{uni_cnt:,}" if uni_cnt is not None else "—")
        m4.metric("Tipos de serviço",   f"{svc_cnt:,}" if svc_cnt is not None else "—")

        # ── Comparativo atendentes (se mais de 1 selecionado) ──
        if c_login and len(at_sels) > 1:
            st.markdown("##### Comparativo entre atendentes")
            d_comp = run(f'SELECT "{c_login}" AS Atendente, COUNT(*) AS Total FROM dados {w_at} GROUP BY "{c_login}" ORDER BY Total DESC')
            fig_comp = px.bar(d_comp, x="Atendente", y="Total", color="Atendente",
                              text="Total", title="Total por atendente",
                              height=altura_grafico(len(d_comp), por_item=60))
            fig_comp.update_layout(showlegend=False, xaxis_title=None)
            fig_comp.update_traces(textposition="outside")
            st.plotly_chart(fig_comp, use_container_width=True)

        # ── Comparativo unidades (se mais de 1 selecionada) ──
        if c_unidade and len(uni_sels) > 1:
            st.markdown("##### Comparativo entre unidades")
            d_uni_comp = run(f'SELECT "{c_unidade}" AS Unidade, COUNT(*) AS Total FROM dados {w_at} GROUP BY "{c_unidade}" ORDER BY Total DESC')
            fig_uni = px.bar(d_uni_comp, x="Unidade", y="Total", color="Unidade",
                             text="Total", title="Total por unidade",
                             height=altura_grafico(len(d_uni_comp), por_item=60))
            fig_uni.update_layout(showlegend=False, xaxis_title=None)
            fig_uni.update_traces(textposition="outside")
            st.plotly_chart(fig_uni, use_container_width=True)

        # ── Gráficos ──
        gl, gr = st.columns(2)
        with gl:
            if c_servico:
                d_svc = run(f'SELECT "{c_servico}" AS Servico, COUNT(*) AS Qtd FROM dados {w_at} GROUP BY "{c_servico}" ORDER BY Qtd DESC LIMIT 10')
                fig_s = px.bar(d_svc, x="Qtd", y="Servico", orientation="h",
                               title="Serviços realizados (top 10)",
                               color="Qtd", color_continuous_scale="Teal", text="Qtd",
                               height=altura_grafico(len(d_svc)))
                fig_s.update_layout(coloraxis_showscale=False, yaxis_title=None)
                fig_s.update_traces(textposition="outside")
                st.plotly_chart(fig_s, use_container_width=True)
        with gr:
            if c_unidade and not uni_sels:
                # Só mostra pizza de unidade se não filtrou por unidade específica
                d_uni = run(f'SELECT "{c_unidade}" AS Unidade, COUNT(*) AS Qtd FROM dados {w_at} GROUP BY "{c_unidade}"')
                fig_u = px.pie(d_uni, names="Unidade", values="Qtd", title="Distribuição por unidade")
                st.plotly_chart(fig_u, use_container_width=True)
            elif c_login and not at_sels:
                d_log = run(f'SELECT "{c_login}" AS Atendente, COUNT(*) AS Qtd FROM dados {w_at} GROUP BY "{c_login}" ORDER BY Qtd DESC LIMIT 10')
                fig_l = px.pie(d_log, names="Atendente", values="Qtd", title="Distribuição por atendente")
                st.plotly_chart(fig_l, use_container_width=True)

        # ── Tabela clicável ──
        cols_at = [c for c in [c_nome, c_cpf, c_login, c_servico, c_data, c_unidade] if c]
        col_sel = ", ".join([f'"{c}"' for c in cols_at])
        df_at = run(f"SELECT {col_sel} FROM dados {w_at} LIMIT 500")
        st.markdown("##### Registros — clique em uma linha para ver o perfil do cidadão")
        ev_at = st.dataframe(df_at, use_container_width=True, hide_index=True,
                             on_select="rerun", selection_mode="single-row")

        sel_at = ev_at.selection.rows if hasattr(ev_at, "selection") else []
        if sel_at and c_cpf:
            row_at = df_at.iloc[sel_at[0]]
            cpf_at_sel = str(row_at.get(c_cpf, "")).replace("'", "''")
            if cpf_at_sel:
                st.markdown("---")
                nome_at_sel = row_at.get(c_nome, "Cidadão")
                st.subheader(f"👤 Perfil: {nome_at_sel}")

                total_cpf_at = run_val("SELECT COUNT(*) FROM dados WHERE " + chr(34) + c_cpf + chr(34) + " = '" + cpf_at_sel + "'")
                pa, pb, pc, pd_ = st.columns(4)
                pa.metric("CPF",           cpf_at_sel)
                pb.metric("NIS",           str(row_at.get(c_nis,  "—")))
                pc.metric("Nascimento",    str(row_at.get(c_nasc, "—")))
                pd_.metric("Atendimentos", f"{total_cpf_at:,}")

                cols_h = [c for c in [c_data, c_servico, c_unidade, c_quantia, c_login, c_categoria] if c]
                col_h_sel = ", ".join([f'"{c}"' for c in cols_h])
                df_hist_at = run("SELECT " + col_h_sel + " FROM dados WHERE " + chr(34) + c_cpf + chr(34) + " = '" + cpf_at_sel + "' ORDER BY " + chr(34) + str(c_data or "") + chr(34) + " DESC LIMIT 500")
                st.markdown("##### Histórico completo de serviços")
                st.dataframe(df_hist_at, use_container_width=True, hide_index=True)

                if c_servico and not df_hist_at.empty:
                    svc_at_c = run("SELECT " + chr(34) + c_servico + chr(34) + " AS Servico, COUNT(*) AS Qtd FROM dados WHERE " + chr(34) + c_cpf + chr(34) + " = '" + cpf_at_sel + "' GROUP BY " + chr(34) + c_servico + chr(34) + " ORDER BY Qtd DESC")
                    fig_h = px.bar(svc_at_c, x="Qtd", y="Servico", orientation="h",
                                   title="Serviços recebidos", color="Qtd",
                                   color_continuous_scale="Blues", text="Qtd")
                    fig_h.update_layout(coloraxis_showscale=False, yaxis_title=None, xaxis_title="Quantidade")
                    fig_h.update_traces(textposition="outside")
                    st.plotly_chart(fig_h, use_container_width=True)
        # ── Exportar desta seleção ──
        st.markdown("---")
        st.markdown("##### 📥 Exportar dados desta seleção")
        EXPORT_LIMIT_AT = 50_000
        col_at_exp = [c for c in [c_nome, c_cpf, c_nis, c_nasc, c_login, c_servico, c_data, c_unidade, c_categoria] if c]
        df_at_exp = run("SELECT " + ", ".join([chr(34)+c+chr(34) for c in col_at_exp]) + " FROM dados " + w_at + " LIMIT " + str(EXPORT_LIMIT_AT))
        out_at = io.BytesIO()
        with pd.ExcelWriter(out_at, engine="openpyxl") as writer:
            df_at_exp.to_excel(writer, index=False, sheet_name="Atendimentos")
            if c_login:
                run("SELECT " + chr(34) + c_login + chr(34) + " AS Atendente, COUNT(*) AS Total FROM dados " + w_at + " GROUP BY " + chr(34) + c_login + chr(34) + " ORDER BY Total DESC").to_excel(writer, index=False, sheet_name="Por Atendente")
            if c_servico:
                run("SELECT " + chr(34) + c_servico + chr(34) + " AS Servico, COUNT(*) AS Total FROM dados " + w_at + " GROUP BY " + chr(34) + c_servico + chr(34) + " ORDER BY Total DESC").to_excel(writer, index=False, sheet_name="Por Serviço")
            if c_unidade:
                run("SELECT " + chr(34) + c_unidade + chr(34) + " AS Unidade, COUNT(*) AS Total FROM dados " + w_at + " GROUP BY " + chr(34) + c_unidade + chr(34) + " ORDER BY Total DESC").to_excel(writer, index=False, sheet_name="Por Unidade")
        st.download_button("⬇️ Baixar Excel desta seleção", out_at.getvalue(), "atendimentos_selecao.xlsx",
                           "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                           use_container_width=True)
    else:
        st.info("Selecione ao menos um atendente ou uma unidade para ver os dados.")

# ─────────────────────────────────────
# ABA 4 — ALERTAS
# ─────────────────────────────────────
with aba_alertas:
    st.subheader("🚨 Alertas e indicadores")
    st.caption("Indicadores automáticos para apoio à gestão.")

    al1, al2 = st.columns(2)

    # ── Alerta 1: Cidadãos com muitos atendimentos ──
    with al1:
        if c_cpf and c_nome:
            st.markdown("##### ⚠️ Cidadãos com alta frequência")
            limite = st.number_input("Mínimo de atendimentos", min_value=2, max_value=100, value=10, step=1, key="limite_alerta")
            df_freq = run(
                "SELECT " + chr(34) + c_nome + chr(34) + " AS Nome, " +
                chr(34) + c_cpf + chr(34) + " AS CPF, COUNT(*) AS Total " +
                "FROM dados " + where_sql +
                " GROUP BY " + chr(34) + c_cpf + chr(34) + ", " + chr(34) + c_nome + chr(34) +
                " HAVING COUNT(*) >= " + str(int(limite)) +
                " ORDER BY Total DESC LIMIT 50"
            )
            if df_freq.empty:
                st.success(f"✅ Nenhum cidadão com {int(limite)}+ atendimentos.")
            else:
                st.warning(f"{len(df_freq)} cidadão(s) com {int(limite)}+ atendimentos")
                ev_freq = st.dataframe(df_freq, use_container_width=True, hide_index=True,
                                       on_select="rerun", selection_mode="single-row")
                sel_freq = ev_freq.selection.rows if hasattr(ev_freq, "selection") else []
                if sel_freq and c_cpf:
                    row_f = df_freq.iloc[sel_freq[0]]
                    cpf_f = esc(str(row_f["CPF"]))
                    st.markdown("---")
                    st.subheader(f"👤 Perfil: {row_f['Nome']}")
                    tot_f = run_val("SELECT COUNT(*) FROM dados WHERE " + chr(34) + c_cpf + chr(34) + " = '" + cpf_f + "'")
                    pfa, pfb, pfc, pfd = st.columns(4)
                    pfa.metric("CPF", cpf_f)
                    cols_pf = [c for c in [c_nis, c_nasc] if c]
                    if cols_pf:
                        df_pf = get_con().execute("SELECT " + ", ".join([chr(34)+c+chr(34) for c in cols_pf]) + " FROM dados WHERE " + chr(34) + c_cpf + chr(34) + " = '" + cpf_f + "' LIMIT 1").df()
                        pfb.metric("NIS",        str(df_pf.iloc[0][c_nis])  if c_nis  and not df_pf.empty else "—")
                        pfc.metric("Nascimento", str(df_pf.iloc[0][c_nasc]) if c_nasc and not df_pf.empty else "—")
                    pfd.metric("Atendimentos", f"{tot_f:,}")
                    cols_hf = [c for c in [c_data, c_servico, c_unidade, c_login, c_categoria] if c]
                    df_hf = run("SELECT " + ", ".join([chr(34)+c+chr(34) for c in cols_hf]) + " FROM dados WHERE " + chr(34) + c_cpf + chr(34) + " = '" + cpf_f + "' ORDER BY " + chr(34) + str(c_data or "") + chr(34) + " DESC LIMIT 200")
                    st.dataframe(df_hf, use_container_width=True, hide_index=True)

    # ── Alerta 2: Ranking de atendentes (ajustável maior/menor) ──
    with al2:
        if c_login:
            st.markdown("##### 👥 Ranking de atendentes")
            ordem = st.radio("Ordenar por", ["Mais atendimentos", "Menos atendimentos"], horizontal=True, key="ordem_at")
            ordem_sql = "DESC" if ordem == "Mais atendimentos" else "ASC"
            n_at = st.number_input("Quantidade", min_value=3, max_value=40, value=10, step=1, key="n_at")
            try:
                df_rank = run(f'SELECT "{c_login}" AS Atendente, COUNT(*) AS Total FROM dados {where_sql} GROUP BY "{c_login}" ORDER BY Total {ordem_sql} LIMIT {int(n_at)}')
                fig_rank = px.bar(df_rank, x="Total", y="Atendente", orientation="h",
                                  color="Total",
                                  color_continuous_scale="Oranges" if ordem == "Mais atendimentos" else "Reds",
                                  text="Total", height=altura_grafico(len(df_rank)))
                fig_rank.update_layout(coloraxis_showscale=False, yaxis_title=None, xaxis_title="Atendimentos")
                fig_rank.update_traces(textposition="outside")
                st.plotly_chart(fig_rank, use_container_width=True)

                ev_rank = st.dataframe(df_rank, use_container_width=True, hide_index=True,
                                       on_select="rerun", selection_mode="single-row")
                sel_rank = ev_rank.selection.rows if hasattr(ev_rank, "selection") else []
                if sel_rank:
                    at_click = df_rank.iloc[sel_rank[0]]["Atendente"]
                    at_safe = esc(str(at_click))
                    w_atc = "WHERE " + chr(34) + c_login + chr(34) + " = '" + at_safe + "'"
                    st.markdown(f"**Detalhes: {at_click}**")
                    cols_atd = [c for c in [c_nome, c_cpf, c_servico, c_data, c_unidade] if c]
                    df_atd = run("SELECT " + ", ".join([chr(34)+c+chr(34) for c in cols_atd]) + " FROM dados " + w_atc + " LIMIT 200")
                    st.dataframe(df_atd, use_container_width=True, hide_index=True)
            except Exception as e:
                st.caption(f"Indisponível: {e}")

    # ── Alerta 3: Cidadãos sem retorno ──
    st.markdown("---")
    st.markdown("##### 🔍 Cidadãos com apenas 1 atendimento (busca ativa)")
    if c_cpf and c_nome:
        try:
            df_sem_ret = run(
                "SELECT " + chr(34) + c_nome + chr(34) + " AS Nome, " +
                chr(34) + c_cpf + chr(34) + " AS CPF, " +
                "MIN(CAST(" + chr(34) + str(c_data or "") + chr(34) + " AS DATE)) AS Ultimo_atendimento " +
                "FROM dados " + where_sql +
                " GROUP BY " + chr(34) + c_cpf + chr(34) + ", " + chr(34) + c_nome + chr(34) +
                " HAVING COUNT(*) = 1 ORDER BY Ultimo_atendimento ASC LIMIT 100"
            )
            if df_sem_ret.empty:
                st.success("✅ Nenhum cidadão com apenas 1 atendimento.")
            else:
                st.info(f"{len(df_sem_ret)} cidadão(s) com apenas 1 atendimento — mostrando os 100 com atendimento mais antigo")
                ev_sr = st.dataframe(df_sem_ret, use_container_width=True, hide_index=True,
                                     on_select="rerun", selection_mode="single-row")
                sel_sr = ev_sr.selection.rows if hasattr(ev_sr, "selection") else []
                if sel_sr and c_cpf:
                    row_sr = df_sem_ret.iloc[sel_sr[0]]
                    cpf_sr = esc(str(row_sr["CPF"]))
                    st.markdown("---")
                    st.subheader(f"👤 Perfil: {row_sr['Nome']}")
                    tot_sr = run_val("SELECT COUNT(*) FROM dados WHERE " + chr(34) + c_cpf + chr(34) + " = '" + cpf_sr + "'")
                    sa, sb, sc_, sd = st.columns(4)
                    sa.metric("CPF", cpf_sr)
                    cols_ps = [c for c in [c_nis, c_nasc] if c]
                    if cols_ps:
                        df_ps = get_con().execute("SELECT " + ", ".join([chr(34)+c+chr(34) for c in cols_ps]) + " FROM dados WHERE " + chr(34) + c_cpf + chr(34) + " = '" + cpf_sr + "' LIMIT 1").df()
                        sb.metric("NIS",        str(df_ps.iloc[0][c_nis])  if c_nis  and not df_ps.empty else "—")
                        sc_.metric("Nascimento",str(df_ps.iloc[0][c_nasc]) if c_nasc and not df_ps.empty else "—")
                    sd.metric("Atendimentos", tot_sr)
                    cols_hs = [c for c in [c_data, c_servico, c_unidade, c_login] if c]
                    df_hs = run("SELECT " + ", ".join([chr(34)+c+chr(34) for c in cols_hs]) + " FROM dados WHERE " + chr(34) + c_cpf + chr(34) + " = '" + cpf_sr + "' LIMIT 100")
                    st.dataframe(df_hs, use_container_width=True, hide_index=True)
        except Exception as e:
            st.caption(f"Indisponível: {e}")

# ─────────────────────────────────────
# ABA 5 — RECORRÊNCIA ALTERNADA
# ─────────────────────────────────────
with aba_recorr:
    st.subheader("🔄 Recorrência Alternada entre Meses/Anos")
    st.caption(
        "Indivíduos que retornam de forma intermitente — ausência de pelo menos 1 mês entre atendimentos consecutivos. "
        "**Indicativo de não-resolução.** O sucesso é quando o cidadão deixa de solicitar o serviço."
    )

    if not c_cpf or not c_data:
        st.warning("Colunas CPF e DATA são necessárias para esta análise.")
    else:
        col_r1, col_r2, col_r3 = st.columns(3)
        with col_r1:
            min_retornos = st.number_input(
                "Mínimo de retornos alternados", min_value=2, max_value=20, value=2, step=1,
                key="min_retornos",
                help="Quantidade mínima de vezes que o cidadão voltou após ausência de ≥1 mês"
            )
        with col_r2:
            gap_meses = st.number_input(
                "Gap mínimo entre atendimentos (meses)", min_value=1, max_value=12, value=1, step=1,
                key="gap_meses",
                help="Intervalo mínimo em meses para considerar 'alternância'"
            )
        with col_r3:
            f_servico_recorr = st.selectbox(
                "Filtrar por serviço", ["Todos"] + (opts_db(c_servico, "Todos")[1:] if c_servico else []),
                key="servico_recorr"
            )

        w_recorr = where_sql
        if f_servico_recorr != "Todos" and c_servico:
            ao = "AND" if w_recorr else "WHERE"
            w_recorr += f" {ao} \"{c_servico}\" = '{esc(f_servico_recorr)}'"

        # Query: identifica cidadãos com padrão alternado
        # Lógica: agrupa atendimentos por CPF/ano-mês, depois detecta gaps >= gap_meses entre períodos consecutivos
        try:
            nome_col = f', FIRST("{c_nome}") AS Nome' if c_nome else ""
            nome_sel = f'"Nome", ' if c_nome else ""

            sql_recorr = f"""
                WITH periodos AS (
                    SELECT
                        "{c_cpf}" AS CPF
                        {nome_col}
                        , DATE_TRUNC('month', CAST("{c_data}" AS DATE)) AS periodo
                        , COUNT(*) AS atend_no_periodo
                    FROM dados {w_recorr}
                    GROUP BY "{c_cpf}" {',' + chr(34) + c_nome + chr(34) if c_nome else ''}, DATE_TRUNC('month', CAST("{c_data}" AS DATE))
                ),
                com_lag AS (
                    SELECT
                        CPF
                        {', Nome' if c_nome else ''}
                        , periodo
                        , atend_no_periodo
                        , LAG(periodo) OVER (PARTITION BY CPF ORDER BY periodo) AS periodo_anterior
                        , DATEDIFF('month', LAG(periodo) OVER (PARTITION BY CPF ORDER BY periodo), periodo) AS gap_meses_real
                    FROM periodos
                ),
                alternados AS (
                    SELECT
                        CPF
                        {', Nome' if c_nome else ''}
                        , COUNT(*) AS total_retornos_alternados
                        , MIN(periodo) AS primeiro_atendimento
                        , MAX(periodo) AS ultimo_atendimento
                        , SUM(atend_no_periodo) AS total_atendimentos
                        , DATEDIFF('month', MIN(periodo), MAX(periodo)) AS span_meses
                    FROM com_lag
                    WHERE gap_meses_real >= {int(gap_meses)} OR periodo_anterior IS NULL
                    GROUP BY CPF {', Nome' if c_nome else ''}
                    HAVING SUM(CASE WHEN gap_meses_real >= {int(gap_meses)} THEN 1 ELSE 0 END) >= {int(min_retornos)}
                )
                SELECT
                    {nome_sel}CPF
                    , total_retornos_alternados AS "Retornos alternados"
                    , total_atendimentos AS "Total atendimentos"
                    , span_meses AS "Span (meses)"
                    , STRFTIME(primeiro_atendimento, '%m/%Y') AS "Primeiro"
                    , STRFTIME(ultimo_atendimento, '%m/%Y') AS "Último"
                FROM alternados
                ORDER BY total_retornos_alternados DESC, total_atendimentos DESC
                LIMIT 200
            """

            df_recorr = run(sql_recorr)

            if df_recorr.empty:
                st.success("✅ Nenhum cidadão com padrão de recorrência alternada nos parâmetros definidos.")
            else:
                # Métricas resumo
                mr1, mr2, mr3 = st.columns(3)
                mr1.metric("Cidadãos com recorrência alternada", f"{len(df_recorr):,}")
                mr2.metric("Média de retornos alternados", f"{df_recorr['Retornos alternados'].mean():.1f}")
                mr3.metric("Média de span (meses)", f"{df_recorr['Span (meses)'].mean():.1f}")

                st.markdown("---")

                # Gráfico 1: Top cidadãos com mais retornos (bar horizontal — fácil leitura)
                col_g1, col_g2 = st.columns(2)
                with col_g1:
                    top_n = min(15, len(df_recorr))
                    df_top = df_recorr.head(top_n).copy()
                    label_col = "Nome" if c_nome and "Nome" in df_top.columns else "CPF"
                    fig_top = px.bar(
                        df_top.iloc[::-1],  # maior no topo
                        x="Retornos alternados",
                        y=label_col,
                        orientation="h",
                        title=f"Top {top_n} — Mais retornos alternados",
                        color="Retornos alternados",
                        color_continuous_scale=["#fde8e8", "#c0392b"],
                        text="Retornos alternados",
                    )
                    fig_top.update_layout(
                        coloraxis_showscale=False,
                        yaxis_title=None,
                        xaxis_title="Nº de retornos",
                        height=max(300, top_n * 28 + 80),
                    )
                    fig_top.update_traces(textposition="outside")
                    st.plotly_chart(fig_top, use_container_width=True)

                # Gráfico 2: Faixa de span em meses (categorizado — sem jargão técnico)
                with col_g2:
                    def faixa_span(s):
                        if s <= 3:   return "Até 3 meses"
                        elif s <= 6: return "4–6 meses"
                        elif s <= 12: return "7–12 meses"
                        elif s <= 24: return "1–2 anos"
                        else:        return "Mais de 2 anos"

                    df_faixa = df_recorr.copy()
                    df_faixa["Período de recorrência"] = df_faixa["Span (meses)"].apply(faixa_span)
                    ordem_faixa = ["Até 3 meses", "4–6 meses", "7–12 meses", "1–2 anos", "Mais de 2 anos"]
                    faixa_cnt = (
                        df_faixa.groupby("Período de recorrência")
                        .size()
                        .reindex(ordem_faixa)
                        .dropna()
                        .reset_index(name="Cidadãos")
                    )
                    fig_faixa = px.bar(
                        faixa_cnt,
                        x="Período de recorrência",
                        y="Cidadãos",
                        title="Por quanto tempo o cidadão ficou retornando",
                        color="Cidadãos",
                        color_continuous_scale=["#fde8e8", "#c0392b"],
                        text="Cidadãos",
                    )
                    fig_faixa.update_layout(
                        coloraxis_showscale=False,
                        xaxis_title=None,
                        yaxis_title="Nº de cidadãos",
                    )
                    fig_faixa.update_traces(textposition="outside")
                    st.plotly_chart(fig_faixa, use_container_width=True)

                st.markdown("##### Lista de cidadãos — clique para ver o histórico")
                ev_recorr = st.dataframe(
                    df_recorr, use_container_width=True, hide_index=True,
                    on_select="rerun", selection_mode="single-row"
                )

                sel_recorr = ev_recorr.selection.rows if hasattr(ev_recorr, "selection") else []
                if sel_recorr:
                    row_r = df_recorr.iloc[sel_recorr[0]]
                    cpf_r = esc(str(row_r["CPF"]))
                    nome_r = row_r.get("Nome", row_r["CPF"]) if c_nome else row_r["CPF"]

                    st.markdown("---")
                    st.subheader(f"👤 Perfil: {nome_r}")

                    tot_r = run_val(
                        f'SELECT COUNT(*) FROM dados WHERE "{c_cpf}" = \'{cpf_r}\''
                    )

                    cols_id = [c for c in [c_nis, c_nasc] if c]
                    nis_r, nasc_r = "—", "—"
                    if cols_id:
                        df_id = run(
                            "SELECT " + ", ".join([f'"{c}"' for c in cols_id]) +
                            f' FROM dados WHERE "{c_cpf}" = \'{cpf_r}\' LIMIT 1'
                        )
                        if not df_id.empty:
                            if c_nis:
                                nis_r = str(df_id.iloc[0][c_nis])
                            if c_nasc:
                                nasc_r = str(df_id.iloc[0][c_nasc])

                    pr0a, pr0b, pr1, pr2, pr3, pr4 = st.columns(6)
                    pr0a.metric("NIS", nis_r)
                    pr0b.metric("Nascimento", nasc_r)
                    pr1.metric("CPF", cpf_r)
                    pr2.metric("Retornos alternados", int(row_r["Retornos alternados"]))
                    pr3.metric("Span total", f"{int(row_r['Span (meses)'])} meses")
                    pr4.metric("Total atendimentos", f"{tot_r:,}")

                    cols_hr = [c for c in [c_data, c_servico, c_unidade, c_login, c_categoria] if c]
                    df_hr = run(
                        "SELECT " + ", ".join([f'"{c}"' for c in cols_hr]) +
                        f' FROM dados WHERE "{c_cpf}" = \'{cpf_r}\'' +
                        (f' ORDER BY "{c_data}" ASC' if c_data else "") +
                        " LIMIT 500"
                    )

                    # Linha do tempo visual por mês
                    if c_data and not df_hr.empty:
                        st.markdown("##### 📅 Linha do tempo de atendimentos")
                        df_hr_dt = df_hr.copy()
                        df_hr_dt["_mes"] = pd.to_datetime(df_hr_dt[c_data], errors="coerce").dt.to_period("M").astype(str)
                        timeline = df_hr_dt.groupby("_mes").size().reset_index(name="Atendimentos")
                        timeline.columns = ["Mês", "Atendimentos"]

                        fig_tl = px.bar(
                            timeline, x="Mês", y="Atendimentos",
                            title="Atendimentos por mês",
                            color="Atendimentos",
                            color_continuous_scale=["#fde8e8", "#e05252"],
                            text="Atendimentos"
                        )
                        fig_tl.update_layout(
                            coloraxis_showscale=False,
                            xaxis_tickangle=-45,
                            xaxis_title=None
                        )
                        fig_tl.update_traces(textposition="outside")
                        st.plotly_chart(fig_tl, use_container_width=True)

                        # Identificar gaps visualmente
                        if len(timeline) > 1:
                            timeline["_periodo"] = pd.to_datetime(timeline["Mês"])
                            timeline = timeline.sort_values("_periodo")
                            gaps = timeline["_periodo"].diff().dt.days.fillna(0)
                            gaps_reais = [(timeline.iloc[i]["Mês"], int(g // 30)) for i, g in enumerate(gaps) if g >= gap_meses * 28 and i > 0]
                            if gaps_reais:
                                with st.expander(f"⏸️ {len(gaps_reais)} intervalo(s) de ausência detectado(s)"):
                                    for mes, g in gaps_reais:
                                        st.markdown(f"- Retornou em **{mes}** após ~**{g} meses** sem atendimento")

                    st.markdown("##### Histórico completo")
                    st.dataframe(df_hr, use_container_width=True, hide_index=True)

                    # Gráfico por serviço
                    if c_servico and not df_hr.empty:
                        svc_r = run(
                            f'SELECT "{c_servico}" AS Servico, COUNT(*) AS Qtd FROM dados '
                            f'WHERE "{c_cpf}" = \'{cpf_r}\' GROUP BY "{c_servico}" ORDER BY Qtd DESC'
                        )
                        fig_sr = px.bar(
                            svc_r, x="Qtd", y="Servico", orientation="h",
                            title="Serviços solicitados", color="Qtd",
                            color_continuous_scale="Reds", text="Qtd"
                        )
                        fig_sr.update_layout(coloraxis_showscale=False, yaxis_title=None)
                        fig_sr.update_traces(textposition="outside")
                        st.plotly_chart(fig_sr, use_container_width=True)

                # Exportar lista
                st.markdown("---")
                out_r = io.BytesIO()
                with pd.ExcelWriter(out_r, engine="openpyxl") as writer:
                    df_recorr.to_excel(writer, index=False, sheet_name="Recorrência Alternada")
                st.download_button(
                    "⬇️ Exportar lista de recorrência alternada", out_r.getvalue(),
                    "recorrencia_alternada.xlsx",
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True
                )

        except Exception as e:
            st.error(f"Erro na análise de recorrência: {e}")

# ─────────────────────────────────────
# ABA 6 — CADÚNICO (cruzamento)
# ─────────────────────────────────────
with aba_cad:
    st.subheader("🔗 Cruzamento com o CadÚnico")
    st.caption("Identifica cidadãos presentes nas duas bases e padrões de entrada/saída no CadÚnico.")

    if not cadunico_loaded:
        st.info("📂 Carregue ao menos 1 arquivo do CadÚnico na barra lateral para usar esta aba.")
    elif not c_cpf:
        st.warning("A base de Atendimentos precisa ter coluna de CPF para fazer o cruzamento.")
    else:
        con = get_con()

        # Última competência carregada do CadÚnico
        ultima_ref = con.execute("SELECT MAX(ref_cad) FROM cadunico").fetchone()[0]
        st.caption(f"Competência mais recente do CadÚnico carregada: **{ultima_ref}**")

        sub1, sub2, sub3 = st.tabs([
            "✅ Atualmente nos 2 bancos",
            "🔁 3+ ciclos no CadÚnico",
            "🪪 Sem CPF (via NIS)"
        ])

        # ── Cruzamento 1: atualmente nos dois bancos ──
        with sub1:
            st.markdown("##### Pessoas com registro atual no CadÚnico **e** com atendimento no período carregado")
            try:
                sql_atual = f"""
                    WITH cad_atual AS (
                        SELECT DISTINCT cpf, nis, nome, nascimento
                        FROM cadunico
                        WHERE ref_cad = (SELECT MAX(ref_cad) FROM cadunico)
                          AND cpf IS NOT NULL
                    ),
                    atend_cpf AS (
                        SELECT DISTINCT "{c_cpf}" AS cpf
                        FROM dados {where_sql}
                    )
                    SELECT
                        ca.nome AS Nome,
                        ca.cpf AS CPF,
                        ca.nis AS NIS,
                        ca.nascimento AS Nascimento
                    FROM cad_atual ca
                    INNER JOIN atend_cpf a ON a.cpf = ca.cpf
                    ORDER BY ca.nome
                    LIMIT 1000
                """
                df_atual = con.execute(sql_atual).df()

                if df_atual.empty:
                    st.success("✅ Nenhuma coincidência encontrada entre os filtros atuais.")
                else:
                    st.metric("Pessoas nos dois bancos atualmente", f"{len(df_atual):,}")
                    ev_atual = st.dataframe(
                        df_atual, use_container_width=True, hide_index=True,
                        on_select="rerun", selection_mode="single-row"
                    )
                    sel_atual = ev_atual.selection.rows if hasattr(ev_atual, "selection") else []
                    if sel_atual:
                        row_a = df_atual.iloc[sel_atual[0]]
                        cpf_a = esc(str(row_a["CPF"]))
                        st.markdown("---")
                        st.subheader(f"👤 Perfil: {row_a['Nome']}")
                        pa1, pa2, pa3, pa4 = st.columns(4)
                        pa1.metric("CPF", row_a["CPF"])
                        pa2.metric("NIS", row_a["NIS"] if row_a["NIS"] else "—")
                        pa3.metric("Nascimento", row_a["Nascimento"] if row_a["Nascimento"] else "—")
                        tot_a = run_val(f'SELECT COUNT(*) FROM dados WHERE "{c_cpf}" = \'{cpf_a}\'')
                        pa4.metric("Atendimentos", f"{tot_a:,}")

                        cols_ha = [c for c in [c_data, c_servico, c_unidade, c_login, c_categoria] if c]
                        df_ha = run(
                            "SELECT " + ", ".join([f'"{c}"' for c in cols_ha]) +
                            f' FROM dados WHERE "{c_cpf}" = \'{cpf_a}\'' +
                            (f' ORDER BY "{c_data}" DESC' if c_data else "") + " LIMIT 200"
                        )
                        st.dataframe(df_ha, use_container_width=True, hide_index=True)

                    out_atual = io.BytesIO()
                    with pd.ExcelWriter(out_atual, engine="openpyxl") as writer:
                        df_atual.to_excel(writer, index=False, sheet_name="Nos 2 bancos")
                    st.download_button(
                        "⬇️ Exportar lista", out_atual.getvalue(), "cadunico_atendimentos_atual.xlsx",
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        use_container_width=True, key="dl_atual"
                    )
            except Exception as e:
                st.error(f"Erro no cruzamento: {e}")

        # ── Cruzamento 2: 3+ ciclos de entrada/saída no CadÚnico ──
        with sub2:
            st.markdown("##### Pessoas com 3 ou mais ciclos de entrada/saída no CadÚnico")
            st.caption("Um ciclo termina quando há um mês de ausência seguido de retorno ao programa.")
            min_ciclos = st.number_input("Mínimo de ciclos", min_value=2, max_value=20, value=3, step=1, key="min_ciclos_cad")
            try:
                sql_ciclos = f"""
                    WITH presencas AS (
                        SELECT DISTINCT cpf, nome, nis, nascimento,
                               STRPTIME(ref_cad, '%d/%m/%Y') AS periodo
                        FROM cadunico
                        WHERE cpf IS NOT NULL
                    ),
                    com_lag AS (
                        SELECT
                            cpf, nome, nis, nascimento, periodo,
                            LAG(periodo) OVER (PARTITION BY cpf ORDER BY periodo) AS periodo_anterior,
                            DATEDIFF('month', LAG(periodo) OVER (PARTITION BY cpf ORDER BY periodo), periodo) AS gap
                        FROM presencas
                    ),
                    ciclos AS (
                        SELECT
                            cpf,
                            FIRST(nome) AS nome,
                            FIRST(nis) AS nis,
                            FIRST(nascimento) AS nascimento,
                            SUM(CASE WHEN gap >= 2 THEN 1 ELSE 0 END) + 1 AS num_ciclos,
                            MIN(periodo) AS primeiro,
                            MAX(periodo) AS ultimo,
                            COUNT(*) AS total_meses_presente
                        FROM com_lag
                        GROUP BY cpf
                        HAVING SUM(CASE WHEN gap >= 2 THEN 1 ELSE 0 END) + 1 >= {int(min_ciclos)}
                    )
                    SELECT
                        nome AS Nome,
                        cpf AS CPF,
                        nis AS NIS,
                        nascimento AS Nascimento,
                        num_ciclos AS "Ciclos no CadÚnico",
                        total_meses_presente AS "Meses presente",
                        STRFTIME(primeiro, '%m/%Y') AS "Primeiro registro",
                        STRFTIME(ultimo, '%m/%Y') AS "Último registro"
                    FROM ciclos
                    ORDER BY num_ciclos DESC, total_meses_presente DESC
                    LIMIT 500
                """
                df_ciclos = con.execute(sql_ciclos).df()

                if df_ciclos.empty:
                    st.success(f"✅ Nenhuma pessoa com {int(min_ciclos)}+ ciclos detectados.")
                else:
                    mc1, mc2 = st.columns(2)
                    mc1.metric("Pessoas com ciclos repetidos", f"{len(df_ciclos):,}")
                    mc2.metric("Média de ciclos", f"{df_ciclos['Ciclos no CadÚnico'].mean():.1f}")

                    top_n_cad = min(15, len(df_ciclos))
                    df_top_cad = df_ciclos.head(top_n_cad).copy()
                    fig_ciclos = px.bar(
                        df_top_cad.iloc[::-1],
                        x="Ciclos no CadÚnico", y="Nome", orientation="h",
                        title=f"Top {top_n_cad} — Mais ciclos de entrada/saída",
                        color="Ciclos no CadÚnico",
                        color_continuous_scale=["#fde8e8", "#c0392b"],
                        text="Ciclos no CadÚnico",
                        height=max(300, top_n_cad * 28 + 80),
                    )
                    fig_ciclos.update_layout(coloraxis_showscale=False, yaxis_title=None, xaxis_title="Nº de ciclos")
                    fig_ciclos.update_traces(textposition="outside")
                    st.plotly_chart(fig_ciclos, use_container_width=True)

                    st.markdown("##### Lista completa — clique para ver atendimentos")
                    ev_ciclos = st.dataframe(
                        df_ciclos, use_container_width=True, hide_index=True,
                        on_select="rerun", selection_mode="single-row"
                    )
                    sel_ciclos = ev_ciclos.selection.rows if hasattr(ev_ciclos, "selection") else []
                    if sel_ciclos:
                        row_c = df_ciclos.iloc[sel_ciclos[0]]
                        cpf_c = esc(str(row_c["CPF"]))
                        st.markdown("---")
                        st.subheader(f"👤 Perfil: {row_c['Nome']}")
                        pc1, pc2, pc3, pc4, pc5 = st.columns(5)
                        pc1.metric("CPF", row_c["CPF"])
                        pc2.metric("NIS", row_c["NIS"] if row_c["NIS"] else "—")
                        pc3.metric("Nascimento", row_c["Nascimento"] if row_c["Nascimento"] else "—")
                        pc4.metric("Ciclos", int(row_c["Ciclos no CadÚnico"]))
                        if c_cpf:
                            tot_c = run_val(f'SELECT COUNT(*) FROM dados WHERE "{c_cpf}" = \'{cpf_c}\'')
                            pc5.metric("Atendimentos", f"{tot_c:,}")
                            cols_hc = [c for c in [c_data, c_servico, c_unidade, c_login, c_categoria] if c]
                            df_hc = run(
                                "SELECT " + ", ".join([f'"{c}"' for c in cols_hc]) +
                                f' FROM dados WHERE "{c_cpf}" = \'{cpf_c}\'' +
                                (f' ORDER BY "{c_data}" DESC' if c_data else "") + " LIMIT 200"
                            )
                            if not df_hc.empty:
                                st.markdown("##### Histórico de atendimentos")
                                st.dataframe(df_hc, use_container_width=True, hide_index=True)
                            else:
                                st.caption("Nenhum atendimento encontrado para este CPF.")

                    out_ciclos = io.BytesIO()
                    with pd.ExcelWriter(out_ciclos, engine="openpyxl") as writer:
                        df_ciclos.to_excel(writer, index=False, sheet_name="Ciclos CadÚnico")
                    st.download_button(
                        "⬇️ Exportar lista", out_ciclos.getvalue(), "cadunico_ciclos.xlsx",
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        use_container_width=True, key="dl_ciclos"
                    )
            except Exception as e:
                st.error(f"Erro na detecção de ciclos: {e}")

        # ── Sub-aba 3: sem CPF, cruzando por NIS ──
        with sub3:
            st.markdown("##### Pessoas do CadÚnico sem CPF, cruzadas por NIS com a base de Atendimentos")
            if not c_nis:
                st.warning("A base de Atendimentos não tem coluna de NIS mapeada — não é possível cruzar por esta via.")
            else:
                try:
                    sql_sem_cpf = f"""
                        WITH cad_sem_cpf AS (
                            SELECT DISTINCT nis, nome, rg, nascimento
                            FROM cadunico
                            WHERE (cpf IS NULL OR cpf = '')
                              AND nis IS NOT NULL
                        ),
                        atend_nis AS (
                            SELECT DISTINCT "{c_nis}" AS nis
                            FROM dados {where_sql}
                            WHERE "{c_nis}" IS NOT NULL
                        )
                        SELECT
                            cs.nome AS Nome,
                            cs.nis AS NIS,
                            cs.rg AS RG,
                            cs.nascimento AS Nascimento
                        FROM cad_sem_cpf cs
                        INNER JOIN atend_nis a ON CAST(a.nis AS VARCHAR) = CAST(cs.nis AS VARCHAR)
                        ORDER BY cs.nome
                        LIMIT 500
                    """
                    df_sem_cpf = con.execute(sql_sem_cpf).df()

                    if df_sem_cpf.empty:
                        st.success("✅ Nenhuma pessoa sem CPF encontrada em comum via NIS.")
                    else:
                        st.metric("Pessoas sem CPF cruzadas por NIS", f"{len(df_sem_cpf):,}")
                        ev_sc = st.dataframe(
                            df_sem_cpf, use_container_width=True, hide_index=True,
                            on_select="rerun", selection_mode="single-row"
                        )
                        sel_sc = ev_sc.selection.rows if hasattr(ev_sc, "selection") else []
                        if sel_sc:
                            row_sc = df_sem_cpf.iloc[sel_sc[0]]
                            nis_sc = esc(str(row_sc["NIS"]))
                            st.markdown("---")
                            st.subheader(f"👤 Perfil: {row_sc['Nome']}")
                            psc1, psc2, psc3 = st.columns(3)
                            psc1.metric("NIS", row_sc["NIS"])
                            psc2.metric("RG", row_sc["RG"] if row_sc["RG"] else "—")
                            psc3.metric("Nascimento", row_sc["Nascimento"] if row_sc["Nascimento"] else "—")

                            cols_hsc = [c for c in [c_data, c_servico, c_unidade, c_login, c_categoria] if c]
                            df_hsc = run(
                                "SELECT " + ", ".join([f'"{c}"' for c in cols_hsc]) +
                                f' FROM dados WHERE CAST("{c_nis}" AS VARCHAR) = \'{nis_sc}\'' +
                                (f' ORDER BY "{c_data}" DESC' if c_data else "") + " LIMIT 200"
                            )
                            st.markdown("##### Histórico de atendimentos")
                            st.dataframe(df_hsc, use_container_width=True, hide_index=True)

                        out_sc = io.BytesIO()
                        with pd.ExcelWriter(out_sc, engine="openpyxl") as writer:
                            df_sem_cpf.to_excel(writer, index=False, sheet_name="Sem CPF (via NIS)")
                        st.download_button(
                            "⬇️ Exportar lista", out_sc.getvalue(), "cadunico_sem_cpf.xlsx",
                            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            use_container_width=True, key="dl_sem_cpf"
                        )
                except Exception as e:
                    st.error(f"Erro no cruzamento por NIS: {e}")

# ─────────────────────────────────────
# ABA 7 — EXPORTAR
# ─────────────────────────────────────
with aba_exp:
    st.subheader("Exportar dados filtrados")
    st.caption(f"{total_f:,} registros com os filtros atuais.")
    EXPORT_LIMIT = 50_000
    st.info(f"Exportação limitada a {EXPORT_LIMIT:,} registros por vez.")
    df_exp = run(f"SELECT * FROM dados {where_sql} LIMIT {EXPORT_LIMIT}")
    out = io.BytesIO()
    with pd.ExcelWriter(out, engine="openpyxl") as writer:
        df_exp.to_excel(writer, index=False, sheet_name="Atendimentos")
        if c_login:
            run(f'SELECT "{c_login}" AS Atendente, COUNT(*) AS Total FROM dados {where_sql} GROUP BY "{c_login}" ORDER BY Total DESC').to_excel(writer, index=False, sheet_name="Por Atendente")
        if c_unidade:
            run(f'SELECT "{c_unidade}" AS Unidade, COUNT(*) AS Total FROM dados {where_sql} GROUP BY "{c_unidade}" ORDER BY Total DESC').to_excel(writer, index=False, sheet_name="Por Unidade")
        if c_servico:
            run(f'SELECT "{c_servico}" AS Servico, COUNT(*) AS Total FROM dados {where_sql} GROUP BY "{c_servico}" ORDER BY Total DESC').to_excel(writer, index=False, sheet_name="Por Serviço")
    st.download_button("⬇️ Baixar Excel com resumos", out.getvalue(), "atendimentos.xlsx",
                       "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                       use_container_width=True)