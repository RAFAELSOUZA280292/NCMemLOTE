import re
import io
import time
import requests
import pandas as pd
import streamlit as st
from pathlib import Path
from requests.adapters import HTTPAdapter, Retry

# =========================================
# Config da Página
# =========================================
st.set_page_config(
    page_title="Consulta NCM - Lavoratory",
    layout="centered",
    initial_sidebar_state="collapsed"
)

# =========================================
# Estilo (Dark + Amarelo Riqueza)
# =========================================
st.markdown("""
<style>
    .stApp { background-color: #1A1A1A; color: #EEEEEE; }
    h1, h2, h3, h4, h5, h6 { color: #FFC300; }
    .stTextInput label, .stTextArea label, .stNumberInput label { color: #FFC300; }
    div[data-baseweb="textarea"] > textarea,
    .stTextInput div[data-baseweb="input"] > div,
    .stNumberInput input {
        background-color: #333333 !important;
        color: #EEEEEE !important;
        border: 1px solid #FFC300 !important;
    }
    .stButton > button {
        background-color: #FFC300; color: #1A1A1A;
        border: none; padding: 10px 20px; border-radius: 6px; font-weight: 700;
        transition: background-color 0.25s ease;
    }
    .stButton > button:hover { background-color: #FFD700; color: #000000; }
    .stExpander {
        background-color: #333333; border: 1px solid #FFC300;
        border-radius: 5px; padding: 10px; margin-bottom: 10px;
    }
    .stAlert {
        background-color: #333333; color: #EEEEEE;
        border-left: 5px solid #FFC300; border-radius: 5px;
    }
    hr { border-top: 1px solid #444444; }
</style>
""", unsafe_allow_html=True)

# =========================================
# Logos via pathlib (seguindo seu padrão)
# =========================================
IMAGE_DIR = Path(__file__).resolve().parent.parent / "images"
LOGO_MAIN = IMAGE_DIR / "logo_main.png"
LOGO_RESULT = IMAGE_DIR / "logo_resultado.png"

# =========================================
# Constantes e sessão HTTP com retry
# =========================================
API_BASE = "https://brasilapi.com.br/api/ncm/v1"
HEADERS = {
    "User-Agent": "Lavoratory-NCM/1.0 (+https://lavoratory.com)",
    "Accept": "application/json",
}

session = requests.Session()
retries = Retry(
    total=3,
    backoff_factor=0.4,
    status_forcelist=[429, 500, 502, 503, 504],
    allowed_methods=["GET"]
)
session.mount("https://", HTTPAdapter(max_retries=retries))

# =========================================
# Helpers
# =========================================
def limpar_lista_codigos(raw: str) -> list:
    """Aceita vírgulas, ponto e vírgulas, espaços e quebras de linha. Remove duplicados mantendo a ordem."""
    if not raw:
        return []
    aux = raw
    for s in [";", "\n", "\r", "\t", " "]:
        aux = aux.replace(s, ",")
    parts = [p.strip() for p in aux.split(",") if p.strip()]
    vistos, saida = set(), []
    for p in parts:
        if p not in vistos:
            vistos.add(p)
            saida.append(p)
    return saida

def validar_ncm(code: str) -> tuple:
    """NCM com 8 dígitos numéricos."""
    if not code:
        return False, "Código vazio"
    if not re.fullmatch(r"\d{8}", code):
        return False, "NCM deve ter 8 dígitos numéricos (ex.: 21041019)"
    return True, ""

@st.cache_data(ttl=60*30, show_spinner=False)
def consultar_ncm_exato(code: str) -> tuple:
    """GET /ncm/v1/{code}"""
    try:
        r = session.get(f"{API_BASE}/{code}", headers=HEADERS, timeout=20)
        if r.status_code == 200:
            return 200, r.json()
        return r.status_code, None
    except requests.RequestException:
        return 0, None

@st.cache_data(ttl=60*30, show_spinner=False)
def consultar_ncm_busca(termo: str) -> tuple:
    """GET /ncm/v1?search={termo}"""
    try:
        r = session.get(API_BASE, params={"search": termo}, headers=HEADERS, timeout=20)
        if r.status_code == 200:
            data = r.json()
            return 200, data if isinstance(data, list) else [data]
        return r.status_code, None
    except requests.RequestException:
        return 0, None

def extrair_desc_item(item: dict) -> tuple:
    """Normaliza code/codigo e description/descricao."""
    c = str(item.get("code") or item.get("codigo") or "").strip()
    d = str(item.get("description") or item.get("descricao") or "").strip()
    return c, d

def buscar_ncm(code: str) -> dict:
    """Pipeline completo de busca (exato -> search)."""
    ok, motivo = validar_ncm(code)
    if not ok:
        return {"input_code": code, "code": "", "description": "", "source": "", "status": "invalid", "detail": motivo}

    status, data = consultar_ncm_exato(code)
    if status == 200 and data:
        if isinstance(data, dict):
            c, d = extrair_desc_item(data)
            return {
                "input_code": code,
                "code": c or code,
                "description": d,
                "source": f"{API_BASE}/{code}",
                "status": "ok" if d else "not_found",
                "detail": "" if d else "Sem descrição no retorno do endpoint exato"
            }
        elif isinstance(data, list) and data:
            for item in data:
                c, d = extrair_desc_item(item)
                if c == code:
                    return {
                        "input_code": code,
                        "code": c or code,
                        "description": d,
                        "source": f"{API_BASE}/{code}",
                        "status": "ok" if d else "not_found",
                        "detail": "" if d else "Sem descrição (lista)"
                    }

    if status not in (200, 404, 422, 0):
        return {"input_code": code, "code": "", "description": "", "source": f"{API_BASE}/{code}",
                "status": "error", "detail": f"HTTP {status} no endpoint exato"}

    status2, data2 = consultar_ncm_busca(code)
    if status2 == 200 and data2:
        for item in data2:
            c, d = extrair_desc_item(item)
            if c == code:
                return {
                    "input_code": code, "code": c or code, "description": d,
                    "source": f"{API_BASE}?search={code}",
                    "status": "ok" if d else "not_found", "detail": "" if d else "Sem descrição no item (search)"
                }
        c, d = extrair_desc_item(data2[0])  # primeiro resultado
        return {
            "input_code": code, "code": c or code, "description": d,
            "source": f"{API_BASE}?search={code}", "status": "ok" if d else "not_found",
            "detail": "Sem match exato; retornado o primeiro da busca"
        }

    if status2 not in (200, 404, 0):
        return {"input_code": code, "code": "", "description": "", "source": f"{API_BASE}?search={code}",
                "status": "error", "detail": f"HTTP {status2} no endpoint search"}

    return {"input_code": code, "code": code, "description": "", "source": "", "status": "not_found", "detail": "Não encontrado"}

def df_para_excel_bytes(df: pd.DataFrame) -> bytes:
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="NCM", index=False)
    return buffer.getvalue()

# =========================================
# UI
# =========================================
if LOGO_MAIN.exists():
    st.image(str(LOGO_MAIN), width=150)

st.markdown("<h1 style='text-align:center;'>Consulta de NCM</h1>", unsafe_allow_html=True)
st.caption("Fonte: BrasilAPI • Endpoint: /api/ncm/v1")

exemplo = "Ex.: 21041019\n44152000, 08011100\n20099000"
ncms_raw = st.text_area(
    "Cole os códigos NCM (um por linha ou separados por vírgula):",
    height=180,
    placeholder=exemplo
)

col1, col2, col3 = st.columns([1, 1, 1.2])
with col1:
    delay = st.number_input(
        "Delay entre chamadas (seg.)", min_value=0.0, max_value=2.0, value=0.05, step=0.05,
        help="Evita saturar a API em listas grandes."
    )
with col2:
    executar = st.button("🔎 Consultar NCMs", type="primary", use_container_width=True)
with col3:
    st.info("Para listas grandes, aumente o delay e use o cache local do app.")

st.markdown("---")

# =========================================
# Execução
# =========================================
if executar:
    codigos = limpar_lista_codigos(ncms_raw)
    if not codigos:
        st.warning("Informe ao menos um NCM.")
        st.stop()

    st.write(f"Consultando **{len(codigos)}** código(s) na BrasilAPI…")
    barra = st.progress(0)
    resultados = []

    for i, code in enumerate(codigos, start=1):
        resultados.append(buscar_ncm(code))
        barra.progress(i / len(codigos))
        if delay:
            time.sleep(delay)

    df = pd.DataFrame(resultados)

    # Ordena por status (ok primeiro), depois pelo input_code
    status_ordem = {"ok": 0, "not_found": 1, "invalid": 2, "error": 3}
    df["status_ord"] = df["status"].map(status_ordem).fillna(9)
    df = df.sort_values(["status_ord", "input_code"]).drop(columns=["status_ord"])

    # Tabela para exibir
    df_show = df.rename(columns={
        "input_code": "NCM (input)",
        "code": "NCM (retorno)",
        "description": "Descrição",
        "source": "Fonte",
        "status": "Status",
        "detail": "Detalhe"
    })[["NCM (input)", "NCM (retorno)", "Descrição", "Status", "Detalhe", "Fonte"]]

    if LOGO_RESULT.exists():
        st.image(str(LOGO_RESULT), width=100)

    st.markdown("## Resultado")
    st.dataframe(df_show, use_container_width=True, hide_index=True)

    # Resumo — AGORA CORRETO
    st.markdown("---")
    st.subheader("Resumo")
    st.write(f"✅ OK: **{(df['status'] == 'ok').sum()}**")
    st.write(f"🔍 Não encontrado: **{(df['status'] == 'not_found').sum()}**")
    st.write(f"⚠️ Inválido: **{(df['status'] == 'invalid').sum()}**")
    st.write(f"❌ Erro API: **{(df['status'] == 'error').sum()}**")

    # Downloads
    st.markdown("---")
    st.subheader("Exportar")
    csv_bytes = df_show.to_csv(index=False).encode("utf-8-sig")
    xlsx_bytes = df_para_excel_bytes(df_show)

    st.download_button("⬇️ Baixar CSV", data=csv_bytes, file_name="consulta_ncm.csv", mime="text/csv")
    st.download_button("⬇️ Baixar Excel", data=xlsx_bytes,
                       file_name="consulta_ncm.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

# =========================================
# Dicas
# =========================================
with st.expander("Dicas e observações"):
    st.markdown("""
- Endpoints usados: **GET /api/ncm/v1/{codigo}** (exato) e **GET /api/ncm/v1?search={termo}** (busca).
- Validação exige **8 dígitos** (ex.: 21041019). Outros formatos serão marcados como inválidos.
- `@st.cache_data` evita bater na API ao repetir as consultas por **30 min**.
- Implementado **retry** com backoff para HTTP 429/5xx.
- Se os logos não existirem no deploy, o app ignora sem quebrar.
    """)
