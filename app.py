import re
import io
import time
import requests
import pandas as pd
import streamlit as st
from pathlib import Path

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
    .stApp {
        background-color: #1A1A1A;
        color: #EEEEEE;
    }
    h1, h2, h3, h4, h5, h6 {
        color: #FFC300;
    }
    /* Inputs */
    .stTextInput label, .stTextArea label, .stNumberInput label {
        color: #FFC300;
    }
    div[data-baseweb="textarea"] > textarea,
    .stTextInput div[data-baseweb="input"] > div,
    .stNumberInput input {
        background-color: #333333 !important;
        color: #EEEEEE !important;
        border: 1px solid #FFC300 !important;
    }
    /* Botões */
    .stButton > button {
        background-color: #FFC300;
        color: #1A1A1A;
        border: none;
        padding: 10px 20px;
        border-radius: 6px;
        font-weight: 700;
        transition: background-color 0.25s ease;
    }
    .stButton > button:hover {
        background-color: #FFD700;
        color: #000000;
    }
    /* Expanders / Alerts */
    .stExpander {
        background-color: #333333;
        border: 1px solid #FFC300;
        border-radius: 5px;
        padding: 10px;
        margin-bottom: 10px;
    }
    .stAlert {
        background-color: #333333;
        color: #EEEEEE;
        border-left: 5px solid #FFC300;
        border-radius: 5px;
    }
    hr { border-top: 1px solid #444444; }
</style>
""", unsafe_allow_html=True)

# =========================================
# Logos via pathlib (segue seu padrão)
# =========================================
IMAGE_DIR = Path(__file__).resolve().parent.parent / "images"
LOGO_MAIN = IMAGE_DIR / "logo_main.png"
LOGO_RESULT = IMAGE_DIR / "logo_resultado.png"

# =========================================
# Constantes
# =========================================
API_BASE = "https://brasilapi.com.br/api/ncm/v1"
HEADERS = {
    "User-Agent": "Lavoratory-NCM/1.0 (+https://lavoratory.com)",
    "Accept": "application/json",
}

# =========================================
# Helpers
# =========================================
def limpar_lista_codigos(raw: str) -> list[str]:
    """
    Aceita lista colada com vírgula, ponto e vírgula, espaço, tabs e quebras de linha.
    Normaliza, remove vazios/duplicados e mantém a ordem.
    """
    if not raw:
        return []
    aux = raw
    for s in [";", "\n", "\r", "\t", " "]:
        aux = aux.replace(s, ",")
    parts = [p.strip() for p in aux.split(",") if p.strip()]
    vistos = set()
    saida = []
    for p in parts:
        if p not in vistos:
            vistos.add(p)
            saida.append(p)
    return saida

def validar_ncm(code: str) -> tuple[bool, str]:
    """
    NCM geralmente são 8 dígitos numéricos, mas a BrasilAPI pode retornar variações.
    Aqui: prioriza 8 dígitos. Retorna (ok, motivo_erro).
    """
    if not code:
        return False, "Código vazio"
    if not re.fullmatch(r"\d{8}", code):
        return False, "NCM deve ter 8 dígitos numéricos (ex.: 21041019)"
    return True, ""

@st.cache_data(ttl=60*30, show_spinner=False)
def consultar_ncm_exato(code: str) -> tuple[int, dict | list | None]:
    """
    Chama GET /ncm/v1/{code}
    Retorna (status_code, json|None)
    """
    try:
        r = requests.get(f"{API_BASE}/{code}", headers=HEADERS, timeout=20)
        if r.status_code == 200:
            return 200, r.json()
        return r.status_code, None
    except requests.RequestException:
        return 0, None

@st.cache_data(ttl=60*30, show_spinner=False)
def consultar_ncm_busca(termo: str) -> tuple[int, list | None]:
    """
    Chama GET /ncm/v1?search={termo}
    Retorna (status_code, list|None)
    """
    try:
        r = requests.get(API_BASE, params={"search": termo}, headers=HEADERS, timeout=20)
        if r.status_code == 200:
            data = r.json()
            if isinstance(data, list):
                return 200, data
            return 200, [data]  # fallback defensivo
        return r.status_code, None
    except requests.RequestException:
        return 0, None

def extrair_desc_item(item: dict) -> tuple[str, str]:
    """
    Normaliza campos comuns que variam entre 'code/codigo' e 'description/descricao'
    """
    c = str(item.get("code") or item.get("codigo") or "").strip()
    d = str(item.get("description") or item.get("descricao") or "").strip()
    return c, d

def buscar_ncm(code: str) -> dict:
    """
    Pipeline:
    1) valida 8 dígitos
    2) tenta exato /v1/{code}
    3) fallback search ?search={code} (match exato; se não houver, pega o 1º)
    Retorna dict: {input_code, code, description, source, status, detail}
    """
    ok, motivo = validar_ncm(code)
    if not ok:
        return {
            "input_code": code,
            "code": "",
            "description": "",
            "source": "",
            "status": "invalid",
            "detail": motivo
        }

    # 1) exato
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
        return {
            "input_code": code,
            "code": "",
            "description": "",
            "source": f"{API_BASE}/{code}",
            "status": "error",
            "detail": f"HTTP {status} no endpoint exato"
        }

    # 2) fallback: busca
    status2, data2 = consultar_ncm_busca(code)
    if status2 == 200 and data2:
        # tenta match exato
        for item in data2:
            c, d = extrair_desc_item(item)
            if c == code:
                return {
                    "input_code": code,
                    "code": c or code,
                    "description": d,
                    "source": f"{API_BASE}?search={code}",
                    "status": "ok" if d else "not_found",
                    "detail": "" if d else "Sem descrição no item (search)"
                }
        # senão, pega o 1º resultado (útil para buscas por descrição)
        c, d = extrair_desc_item(data2[0])
        return {
            "input_code": code,
            "code": c or code,
            "description": d,
            "source": f"{API_BASE}?search={code}",
            "status": "ok" if d else "not_found",
            "detail": "Sem match exato; retornado o primeiro da busca"
        }

    if status2 not in (200, 404, 0):
        return {
            "input_code": code,
            "code": "",
            "description": "",
            "source": f"{API_BASE}?search={code}",
            "status": "error",
            "detail": f"HTTP {status2} no endpoint search"
        }

    # Nada encontrado
    return {
        "input_code": code,
        "code": code,
        "description": "",
        "source": "",
        "status": "not_found",
        "detail": "Não encontrado"
    }

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
st.caption("Fonte: BrasilAPI • Endpoint: <code>/api/ncm/v1</code>")

exemplo = "Ex.: 21041019\\n44152000, 08011100\\n20099000"
ncms_raw = st.text_area(
    "Cole os códigos NCM (um por linha ou separados por vírgula):",
    height=180,
    placeholder=exemplo
)

col1, col2, col3 = st.columns([1, 1, 1.2])
with col1:
    delay = st.number_input(
        "Delay entre chamadas (seg.)",
        min_value=0.0, max_value=2.0, value=0.05, step=0.05,
        help="Evita saturar a API em listas grandes."
    )
with col2:
    executar = st.button("🔎 Consultar NCMs", type="primary", use_container_width=True)
with col3:
    st.info("A BrasilAPI está em constante evolução. Para volumes muito grandes, considere cache/local staging.")

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

    erros = 0
    nao_encontrados = 0
    invalidos = 0

    for i, code in enumerate(codigos, start=1):
        res = buscar_ncm(code)
        resultados.append(res)

        if res["status"] == "error":
            erros += 1
        elif res["status"] == "not_found":
            nao_encontrados += 1
        elif res["status"] == "invalid":
            invalidos += 1

        barra.progress(i / len(codigos))
        if delay:
            time.sleep(delay)

    df = pd.DataFrame(resultados)
    # Ordena por status (ok primeiro), depois pelo input_code
    status_ordem = {"ok": 0, "not_found": 1, "invalid": 2, "error": 3}
    df["status_ord"] = df["status"].map(status_ordem).fillna(9)
    df = df.sort_values(["status_ord", "input_code"]).drop(columns=["status_ord"])

    # Colunas mais amigáveis
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

    # Resumo
    st.markdown("---")
    st.subheader("Resumo")
    st.write(f"✅ OK: **{(df['Status'] == 'ok').sum()}**")
    st.write(f"🔍 Não encontrado: **{(df['Status'] == 'not_found').sum()}**")
    st.write(f"⚠️ Inválido: **{(df['Status'] == 'invalid').sum()}**")
    st.write(f"❌ Erro API: **{(df['Status'] == 'error').sum()}**")

    # Downloads
    st.markdown("---")
    st.subheader("Exportar")
    csv_bytes = df_show.to_csv(index=False).encode("utf-8-sig")
    xlsx_bytes = df_para_excel_bytes(df_show)

    st.download_button(
        "⬇️ Baixar CSV",
        data=csv_bytes,
        file_name="consulta_ncm.csv",
        mime="text/csv"
    )
    st.download_button(
        "⬇️ Baixar Excel",
        data=xlsx_bytes,
        file_name="consulta_ncm.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

# =========================================
# Dica de uso
# =========================================
with st.expander("Dicas e observações"):
    st.markdown("""
- A API usada é a **BrasilAPI**: `GET /api/ncm/v1/{codigo}` (exato) e `GET /api/ncm/v1?search={termo}` (busca).
- O app valida NCM com **8 dígitos**. Se colar algo diferente, marcará como **inválido**.
- Em listas extensas, aumente o *delay* para evitar *rate limit*.
- O cache (`@st.cache_data`) reduz chamadas repetidas durante 30 minutos.
- Os campos podem variar entre `code/codigo` e `description/descricao`; o app já normaliza.
    """)
