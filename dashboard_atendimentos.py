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
    safe_name = uploaded_file.name.replace("/", "_").replace("\\", "_")
    out_path = os.path.join(CADUNICO_DIR, f"{safe_name}.parquet")

    # NÃO usa cache — reprocessa sempre para evitar Parquets corrompidos de versões anteriores
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

        if melhor_hits < 1:
            # Diagnóstico: mostra primeiras 3 linhas e separadores tentados
            preview_linhas = "\n".join(f"  linha {i}: {l[:120]!r}" for i, l in enumerate(linhas[:5]))
            raise ValueError(
                f"Não encontrei colunas de CPF nem NIS em {uploaded_file.name}.\n"
                f"Primeiras linhas do arquivo:\n{preview_linhas}\n"
                f"Colunas esperadas (ex): p.num_cpf_pessoa, p.num_nis_pessoa_atual"
            )

        import io as _io
        df_raw = pd.read_csv(
            _io.StringIO(raw_text), dtype=str,
            sep=melhor_sep, skiprows=melhor_header_idx, engine="python",
            on_bad_lines="skip"
        )
    else:
        df_raw = pd.read_excel(uploaded_file, dtype=str)

    # Strip em todos os nomes de coluna (remove espaços antes/depois, inclusive " d.col")
    df_raw.columns = [str(c).strip() for c in df_raw.columns]

    col_map = {}
    for key, target in CADUNICO_COLS.items():
        found = _find_col(df_raw.columns, target)
        if found:
            col_map[key] = found

    if "cpf" not in col_map and "nis" not in col_map:
        preview = ", ".join(f"'{c}'" for c in df_raw.columns[:20])
        raise ValueError(
            f"Não encontrei colunas de CPF nem NIS em {uploaded_file.name} "
            f"({df_raw.shape[1]} colunas, sep={repr(melhor_sep)}, header_linha={melhor_header_idx}).\n"
            f"Primeiras colunas lidas: {preview}"
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
aba_reg, aba_alertas, aba_recorr, aba_cad, aba_exp = st.tabs(["📄 Individuos", "🚨 Alertas", "🔄 Recorrência Alternada", "🔗 CadÚnico", "📥 Exportar"])


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
# ABA 2 — ALERTAS
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
# ABA — CADÚNICO / DEMANDA REPRIMIDA
# ─────────────────────────────────────
with aba_cad:
    st.subheader("🔗 CadÚnico — Demanda Reprimida")
    st.caption(
        "**Demanda reprimida**: pessoas cadastradas no CadÚnico que **nunca foram atendidas** ou "
        "que foram atendidas mas **não constam mais** na base de atendimentos. "
        "O cruzamento é feito por CPF."
    )

    if not cadunico_loaded:
        st.info("📂 Carregue ao menos 1 arquivo do CadÚnico na barra lateral para usar esta aba.")
    elif not c_cpf:
        st.warning("A base de Atendimentos precisa ter coluna de CPF para fazer o cruzamento.")
    else:
        con = get_con()

        # Competências disponíveis para escolha
        try:
            refs_disp = con.execute(
                "SELECT DISTINCT ref_cad FROM cadunico WHERE ref_cad IS NOT NULL ORDER BY ref_cad"
            ).df()["ref_cad"].tolist()
        except Exception:
            refs_disp = []

        if not refs_disp:
            st.warning("Nenhuma competência encontrada no CadÚnico carregado.")
        else:
            ref_sel = st.selectbox(
                "📅 Competência do CadÚnico a analisar",
                refs_disp,
                index=len(refs_disp) - 1,
                help="Selecione o mês de referência do CadÚnico para identificar quem está no programa nesse período."
            )

            sub_dr, sub_atendidos, sub_nis = st.tabs([
                "🔴 Demanda reprimida (nunca atendidos)",
                "✅ Atendidos (estão nos dois bancos)",
                "🪪 Sem CPF — cruzamento por NIS"
            ])

            # ── Demanda reprimida ──
            with sub_dr:
                st.markdown("##### Pessoas no CadÚnico que **não** aparecem na base de atendimentos")
                try:
                    sql_dr = f"""
                        WITH cad_ref AS (
                            SELECT DISTINCT
                                cpf, nome, nis, nascimento
                            FROM cadunico
                            WHERE ref_cad = '{esc(ref_sel)}'
                              AND cpf IS NOT NULL AND cpf NOT IN ('', 'nan', 'None')
                        ),
                        cpfs_atendidos AS (
                            SELECT DISTINCT CAST("{c_cpf}" AS VARCHAR) AS cpf
                            FROM dados
                            WHERE "{c_cpf}" IS NOT NULL
                        )
                        SELECT
                            c.nome   AS Nome,
                            c.cpf    AS CPF,
                            c.nis    AS NIS,
                            c.nascimento AS Nascimento
                        FROM cad_ref c
                        LEFT JOIN cpfs_atendidos a ON a.cpf = c.cpf
                        WHERE a.cpf IS NULL
                        ORDER BY c.nome
                        LIMIT 2000
                    """
                    df_dr = con.execute(sql_dr).df()

                    total_cad_ref = con.execute(
                        f"SELECT COUNT(DISTINCT cpf) FROM cadunico WHERE ref_cad = '{esc(ref_sel)}' AND cpf IS NOT NULL"
                    ).fetchone()[0]
                    total_atendidos_no_cad = total_cad_ref - len(df_dr)

                    m1, m2, m3 = st.columns(3)
                    m1.metric("No CadÚnico nesta competência", f"{total_cad_ref:,}")
                    m2.metric("🔴 Nunca atendidos (demanda reprimida)", f"{len(df_dr):,}")
                    m3.metric("✅ Já atendidos alguma vez", f"{total_atendidos_no_cad:,}")

                    if not df_dr.empty:
                        pct = len(df_dr) / total_cad_ref * 100 if total_cad_ref > 0 else 0
                        st.progress(min(pct / 100, 1.0), text=f"{pct:.1f}% da base do CadÚnico não foi atendida")

                        st.markdown("##### Lista — clique para ver o histórico no sistema de atendimentos")
                        ev_dr = st.dataframe(
                            df_dr, use_container_width=True, hide_index=True,
                            on_select="rerun", selection_mode="single-row"
                        )
                        sel_dr = ev_dr.selection.rows if hasattr(ev_dr, "selection") else []
                        if sel_dr:
                            row_dr = df_dr.iloc[sel_dr[0]]
                            cpf_dr = esc(str(row_dr["CPF"]))
                            st.markdown("---")
                            st.subheader(f"👤 {row_dr['Nome']}")
                            pd1, pd2, pd3 = st.columns(3)
                            pd1.metric("CPF", row_dr["CPF"])
                            pd2.metric("NIS", row_dr["NIS"] if row_dr["NIS"] else "—")
                            pd3.metric("Nascimento", row_dr["Nascimento"] if row_dr["Nascimento"] else "—")

                            # Verifica se teve algum atendimento histórico (pode ter saído do filtro atual)
                            tot_hist = run_val(f'SELECT COUNT(*) FROM dados WHERE CAST("{c_cpf}" AS VARCHAR) = \'{cpf_dr}\'')
                            if tot_hist > 0:
                                st.info(f"⚠️ Esta pessoa teve **{tot_hist}** atendimento(s) registrado(s) historicamente, mas não consta no período filtrado atualmente.")
                                cols_h = [c for c in [c_data, c_servico, c_unidade, c_categoria] if c]
                                df_h = run(
                                    "SELECT " + ", ".join([f'"{c}"' for c in cols_h]) +
                                    f' FROM dados WHERE CAST("{c_cpf}" AS VARCHAR) = \'{cpf_dr}\'' +
                                    (f' ORDER BY "{c_data}" DESC' if c_data else "") + " LIMIT 100"
                                )
                                st.dataframe(df_h, use_container_width=True, hide_index=True)
                            else:
                                st.warning("❌ Nenhum atendimento encontrado para esta pessoa.")

                        st.markdown("---")
                        out_dr = io.BytesIO()
                        with pd.ExcelWriter(out_dr, engine="openpyxl") as writer:
                            df_dr.to_excel(writer, index=False, sheet_name="Demanda Reprimida")
                        st.download_button(
                            "⬇️ Exportar demanda reprimida", out_dr.getvalue(),
                            f"demanda_reprimida_{ref_sel.replace('/', '-')}.xlsx",
                            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            use_container_width=True, key="dl_dr"
                        )
                    else:
                        st.success("✅ Todos os cadastrados no CadÚnico nesta competência já foram atendidos.")

                except Exception as e:
                    st.error(f"Erro ao calcular demanda reprimida: {e}")

            # ── Atendidos (nos dois bancos) ──
            with sub_atendidos:
                st.markdown("##### Pessoas que estão no CadÚnico **e** foram atendidas")
                try:
                    sql_at2 = f"""
                        WITH cad_ref AS (
                            SELECT DISTINCT cpf, nome, nis, nascimento
                            FROM cadunico
                            WHERE ref_cad = '{esc(ref_sel)}'
                              AND cpf IS NOT NULL AND cpf NOT IN ('', 'nan', 'None')
                        ),
                        atend_agg AS (
                            SELECT
                                CAST("{c_cpf}" AS VARCHAR) AS cpf,
                                COUNT(*) AS total_atendimentos
                                {f', MAX(CAST("{c_data}" AS DATE)) AS ultimo_atendimento' if c_data else ''}
                            FROM dados
                            GROUP BY CAST("{c_cpf}" AS VARCHAR)
                        )
                        SELECT
                            c.nome AS Nome,
                            c.cpf AS CPF,
                            c.nis AS NIS,
                            c.nascimento AS Nascimento,
                            a.total_atendimentos AS "Total atendimentos"
                            {f', STRFTIME(a.ultimo_atendimento, \'%d/%m/%Y\') AS "Último atendimento"' if c_data else ''}
                        FROM cad_ref c
                        INNER JOIN atend_agg a ON a.cpf = c.cpf
                        ORDER BY a.total_atendimentos DESC
                        LIMIT 2000
                    """
                    df_at2 = con.execute(sql_at2).df()

                    st.metric("Pessoas atendidas no CadÚnico desta competência", f"{len(df_at2):,}")

                    ev_at2 = st.dataframe(
                        df_at2, use_container_width=True, hide_index=True,
                        on_select="rerun", selection_mode="single-row"
                    )
                    sel_at2 = ev_at2.selection.rows if hasattr(ev_at2, "selection") else []
                    if sel_at2:
                        row_a2 = df_at2.iloc[sel_at2[0]]
                        cpf_a2 = esc(str(row_a2["CPF"]))
                        st.markdown("---")
                        st.subheader(f"👤 {row_a2['Nome']}")
                        pa1, pa2, pa3, pa4 = st.columns(4)
                        pa1.metric("CPF", row_a2["CPF"])
                        pa2.metric("NIS", row_a2["NIS"] if row_a2["NIS"] else "—")
                        pa3.metric("Nascimento", row_a2["Nascimento"] if row_a2["Nascimento"] else "—")
                        pa4.metric("Atendimentos", f"{int(row_a2['Total atendimentos']):,}")

                        cols_ha2 = [c for c in [c_data, c_servico, c_unidade, c_categoria] if c]
                        df_ha2 = run(
                            "SELECT " + ", ".join([f'"{c}"' for c in cols_ha2]) +
                            f' FROM dados WHERE CAST("{c_cpf}" AS VARCHAR) = \'{cpf_a2}\'' +
                            (f' ORDER BY "{c_data}" DESC' if c_data else "") + " LIMIT 200"
                        )
                        st.markdown("##### Histórico de atendimentos")
                        st.dataframe(df_ha2, use_container_width=True, hide_index=True)

                    out_at2 = io.BytesIO()
                    with pd.ExcelWriter(out_at2, engine="openpyxl") as writer:
                        df_at2.to_excel(writer, index=False, sheet_name="Atendidos no CadÚnico")
                    st.download_button(
                        "⬇️ Exportar lista", out_at2.getvalue(),
                        f"cadunico_atendidos_{ref_sel.replace('/', '-')}.xlsx",
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        use_container_width=True, key="dl_at2"
                    )
                except Exception as e:
                    st.error(f"Erro: {e}")

            # ── Sem CPF — cruzamento por NIS ──
            with sub_nis:
                st.markdown("##### Pessoas sem CPF no CadÚnico, cruzadas pelo NIS com os atendimentos")
                if not c_nis:
                    st.warning("A base de Atendimentos não tem coluna de NIS mapeada.")
                else:
                    try:
                        sql_nis = f"""
                            WITH cad_sem_cpf AS (
                                SELECT DISTINCT nis, nome, rg, nascimento
                                FROM cadunico
                                WHERE ref_cad = '{esc(ref_sel)}'
                                  AND (cpf IS NULL OR cpf IN ('', 'nan', 'None'))
                                  AND nis IS NOT NULL
                            ),
                            atend_nis AS (
                                SELECT DISTINCT CAST("{c_nis}" AS VARCHAR) AS nis
                                FROM dados
                                WHERE "{c_nis}" IS NOT NULL
                            ),
                            cad_sem_cpf_nao_atend AS (
                                SELECT c.*, 'Nunca atendido' AS status
                                FROM cad_sem_cpf c
                                LEFT JOIN atend_nis a ON a.nis = c.nis
                                WHERE a.nis IS NULL
                            )
                            SELECT nome AS Nome, nis AS NIS, rg AS RG, nascimento AS Nascimento, status AS Status
                            FROM cad_sem_cpf_nao_atend
                            ORDER BY nome LIMIT 1000
                        """
                        df_nis = con.execute(sql_nis).df()
                        st.metric("Sem CPF e nunca atendidos (via NIS)", f"{len(df_nis):,}")
                        ev_nis = st.dataframe(df_nis, use_container_width=True, hide_index=True,
                                              on_select="rerun", selection_mode="single-row")
                        sel_nis = ev_nis.selection.rows if hasattr(ev_nis, "selection") else []
                        if sel_nis:
                            row_nis = df_nis.iloc[sel_nis[0]]
                            nis_v = esc(str(row_nis["NIS"]))
                            st.markdown("---")
                            st.subheader(f"👤 {row_nis['Nome']}")
                            pn1, pn2, pn3 = st.columns(3)
                            pn1.metric("NIS", row_nis["NIS"])
                            pn2.metric("RG", row_nis["RG"] if row_nis["RG"] else "—")
                            pn3.metric("Nascimento", row_nis["Nascimento"] if row_nis["Nascimento"] else "—")
                            df_hnis = run(
                                "SELECT " + ", ".join([f'"{c}"' for c in [c for c in [c_data, c_servico, c_unidade] if c]]) +
                                f' FROM dados WHERE CAST("{c_nis}" AS VARCHAR) = \'{nis_v}\'' +
                                (f' ORDER BY "{c_data}" DESC' if c_data else "") + " LIMIT 100"
                            )
                            if not df_hnis.empty:
                                st.dataframe(df_hnis, use_container_width=True, hide_index=True)
                        out_nis = io.BytesIO()
                        with pd.ExcelWriter(out_nis, engine="openpyxl") as writer:
                            df_nis.to_excel(writer, index=False, sheet_name="Sem CPF via NIS")
                        st.download_button("⬇️ Exportar", out_nis.getvalue(), "cadunico_sem_cpf.xlsx",
                                           "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                           use_container_width=True, key="dl_nis")
                    except Exception as e:
                        st.error(f"Erro: {e}")


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