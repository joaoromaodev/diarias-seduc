import os, csv, io, sys, json, time, subprocess
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

from core import (
    ler_arquivo_diaria,
    processar_diarias,
    ler_ressarcimento_xlsx,
    obs_unicas,
    classificar_descricao,
    filtrar_ressarcimento,
    gerar_xlsx_ressarcimento,
    # módulo OF
    ler_of,
    meses_da_of,
    of_para_csv,
    cruzar_of_hibrido,
    gerar_csv_of_saida,
    gerar_csv_of_cadastro,
    gerar_csv_of_nao_encontradas,
)

# ── caminhos ──────────────────────────────────────────────────────────────────
BASE_DIR   = Path(__file__).parent
DATA_DIR   = BASE_DIR / "data"
OF_PATH    = DATA_DIR / "base_of.csv"          # base OF (substitui a folha)
BOT_PATH   = BASE_DIR.parent / "consultasiafe" / "bot_ressarcimento.py"
CHROMEDRIVER = BOT_PATH.parent / "chromedriver.exe"
OBS_PATH   = DATA_DIR / "ress_obs.json"
STATUS_PATH = DATA_DIR / "ress_status.json"
DATA_DIR.mkdir(exist_ok=True)

# O bot SIAFE (Selenium + Chrome visível) só funciona na máquina local (Windows com
# chromedriver). No servidor headless ele fica indisponível e a etapa do bot é
# desabilitada automaticamente — o mesmo app.py serve nos dois ambientes.
BOT_DISPONIVEL = BOT_PATH.exists() and CHROMEDRIVER.exists()

# logo institucional (SEDUC · Governo do Pará) embutido em base64
LOGO_PATH = BASE_DIR / "assets" / "logo-seduc-para.jpeg"

def _logo_data_uri():
    try:
        import base64
        b64 = base64.b64encode(LOGO_PATH.read_bytes()).decode("ascii")
        return f"data:image/jpeg;base64,{b64}"
    except Exception:
        return ""

LOGO_URI = _logo_data_uri()

# ── session state ─────────────────────────────────────────────────────────────
if "msg_base" not in st.session_state:
    st.session_state.msg_base = None  # ("success"|"error", "texto")

# estado do módulo de ressarcimento
if "ress_etapa" not in st.session_state:
    st.session_state.ress_etapa = "upload"   # upload|credenciais|aguardando|revisao
if "ress_registros" not in st.session_state:
    st.session_state.ress_registros = []
if "ress_header" not in st.session_state:
    st.session_state.ress_header = []
if "ress_obs" not in st.session_state:
    st.session_state.ress_obs = []
if "ress_resultados" not in st.session_state:
    st.session_state.ress_resultados = {}    # ob -> descricao

# resultado do processamento (persiste entre reruns dos botões de download)
if "proc_result" not in st.session_state:
    st.session_state.proc_result = None

# ── page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Diárias — SEDUC",
    layout="centered",
    initial_sidebar_state="collapsed",
)

# ── tema — SEDUC-PA / Governo do Pará (design tokens) ─────────────────────────
T = {
    # superfícies / texto
    "bg"          : "#F4F6F8",   # surface-page (neutral-050)
    "card"        : "#FFFFFF",   # surface-card
    "text"        : "#161C24",   # text-strong (neutral-900)
    "text_soft"   : "#3B4452",   # text-body (neutral-700)
    "text_muted"  : "#6B7686",   # text-muted (neutral-500)
    # marca / ação (Azul Pará)
    "accent"      : "#0071CE",   # para-blue
    "accent_hover": "#005AA6",   # para-blue-700
    "accent_active": "#004B8C",  # para-blue-800
    "accent_bg"   : "#E3F0FB",   # para-blue-100
    "accent_text" : "#005AA6",   # eyebrow / links
    # perigo (Vermelho Pará)
    "danger"      : "#EB2939",   # para-red
    "danger_hover": "#C81E2E",   # para-red-700
    # bordas / superfícies auxiliares
    "border"      : "#DDE2E9",   # border-subtle (neutral-200)
    "upload_bg"   : "#F1F7FD",   # para-blue-050
    "upload_bdr"  : "#7FB6E9",   # para-blue-300
    "metric_bg"   : "#FAFBFC",   # neutral-025
    "tab_inactive": "#6B7686",
    "tab_panel"   : "#FFFFFF",
    "btn_disabled": "#BBD8F4",   # para-blue-200
    "btn_dis_txt" : "#FFFFFF",
    "file_bg"     : "#F1F7FD",
    "file_text"   : "#161C24",
    "file_border" : "#DDE2E9",
    # console / terminal
    "console_bg"  : "#161C24",   # neutral-900
    "console_text": "#C5CCD6",   # neutral-300
    "console_bdr" : "#28303B",
    # status (bot) — fundo/texto
    "ok_fg": "#1E8E50",  "ok_bg": "#E0F3E8",
    "vazio_fg": "#B7791F", "vazio_bg": "#FBF0D8",
    "erro_fg": "#C81E2E",  "erro_bg": "#FDE7E9",
    "run_fg": "#005AA6",   "run_bg": "#E3F0FB",
    # cores das linhas do log no terminal
    "log_ts": "#7FB6E9", "log_ok": "#5BD08A", "log_erro": "#F4707B", "log_vazio": "#E0A325",
}

# sombras frias da marca (design tokens)
SH_SM = "0 1px 3px rgba(22,28,36,.08), 0 1px 2px rgba(22,28,36,.04)"
SH_MD = "0 4px 12px rgba(22,28,36,.08), 0 1px 3px rgba(22,28,36,.05)"
# movimento (rápido, ease-out, sem bounce)
DUR  = "180ms"
EASE = "cubic-bezier(0.16, 1, 0.3, 1)"

# ── CSS dinâmico ──────────────────────────────────────────────────────────────
st.markdown(f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Mulish:wght@400;500;600;700;800&family=Roboto+Mono:wght@400;500;600&display=swap');
@import url('https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.min.css');

html, body, [class*="css"], .stApp {{
    font-family: 'Mulish', 'Avenir Next', 'Segoe UI', system-ui, sans-serif !important;
    background-color: {T['bg']} !important;
    color: {T['text']} !important;
    -webkit-font-smoothing: antialiased;
}}

#MainMenu, footer, header, .stDeployButton {{ visibility: hidden; display: none; }}

/* ── cabeçalho institucional ── */
.app-header {{
    background: {T['card']};
    border-radius: 12px 12px 0 0;
    padding: 0.9rem 1.4rem;
    box-shadow: {SH_SM};
    display: flex;
    align-items: center;
    gap: 1.1rem;
    border: 1px solid {T['border']};
    border-bottom: none;
}}
.app-header img.app-logo {{
    height: 34px;
    width: auto;
    display: block;
}}
.app-header .app-divider {{
    width: 1px;
    height: 34px;
    background: {T['border']};
}}
.app-header h1 {{
    font-size: 1.02rem;
    font-weight: 800;
    color: {T['text']};
    margin: 0;
    letter-spacing: -0.02em;
}}
.app-header p {{
    font-size: 0.74rem;
    color: {T['text_muted']};
    margin: 2px 0 0 0;
    font-weight: 500;
}}
.app-header-badge {{
    margin-left: auto;
    background: {T['accent_bg']};
    color: {T['accent_text']};
    font-size: 0.62rem;
    font-weight: 800;
    padding: 0.3rem 0.7rem;
    border-radius: 999px;
    letter-spacing: 0.08em;
    text-transform: uppercase;
}}
/* faixa tricolor (bandeira do Pará) sob o cabeçalho */
.app-stripe {{
    height: 3px;
    width: 100%;
    border-radius: 0 0 3px 3px;
    background: linear-gradient(90deg,
        {T['danger']} 0%, {T['danger']} 22%,
        {T['card']} 22%, {T['card']} 26%,
        {T['accent']} 26%, {T['accent']} 100%);
    margin-bottom: 1.4rem;
}}

/* ── abas ── */
.stTabs [data-baseweb="tab-list"] {{
    background: {T['card']};
    border-radius: 12px 12px 0 0;
    padding: 0 1rem;
    border: 1px solid {T['border']};
    border-bottom: 1px solid {T['border']};
    gap: 0;
}}
.stTabs [data-baseweb="tab"] {{
    font-size: 0.82rem;
    font-weight: 500;
    color: {T['tab_inactive']};
    padding: 0.8rem 1.2rem;
    border-bottom: 2px solid transparent;
    margin-bottom: -1px;
    background: transparent;
}}
.stTabs [aria-selected="true"] {{
    color: {T['accent']} !important;
    border-bottom: 2px solid {T['accent']} !important;
    font-weight: 600;
    background: transparent !important;
}}
.stTabs [data-baseweb="tab-panel"] {{
    background: {T['tab_panel']};
    border-radius: 0 0 12px 12px;
    padding: 1.5rem;
    box-shadow: {SH_SM};
    border: 1px solid {T['border']};
    border-top: none;
}}

/* ── info base ── */
.base-info {{
    background: {T['accent_bg']};
    border-left: 3px solid {T['accent']};
    border-radius: 0 8px 8px 0;
    padding: 0.6rem 1rem;
    font-size: 0.8rem;
    color: {T['accent_text']};
    font-weight: 500;
    margin-bottom: 1.4rem;
}}

/* ── eyebrow / label de seção ── */
.section-title {{
    font-size: 0.7rem;
    font-weight: 800;
    color: {T['accent_text']};
    text-transform: uppercase;
    letter-spacing: 0.08em;
    margin-bottom: 0.45rem;
}}

/* ── caption / texto auxiliar ── */
.stCaption, .stCaption p, [data-testid="stCaptionContainer"] p {{
    color: {T['text_soft']} !important;
    font-size: 0.78rem !important;
}}

/* ── upload ── */
[data-testid="stFileUploader"] section {{
    border: 2px dashed {T['upload_bdr']} !important;
    border-radius: 12px !important;
    background: {T['upload_bg']} !important;
    padding: 2rem 1.5rem !important;
    transition: all 0.2s ease;
}}
[data-testid="stFileUploader"] section:hover {{
    border-color: {T['accent']} !important;
    background: {T['accent_bg']} !important;
}}
[data-testid="stFileUploader"] section small,
[data-testid="stFileUploader"] section span,
[data-testid="stFileUploader"] section p {{
    color: {T['text_soft']} !important;
}}
[data-testid="stFileUploader"] section button {{
    background: {T['card']} !important;
    border: 1.5px solid {T['accent']} !important;
    border-radius: 8px !important;
    color: {T['accent']} !important;
    font-size: 0.8rem !important;
    font-weight: 600 !important;
    padding: 0.4rem 1.2rem !important;
}}
[data-testid="stFileUploader"] section button:hover {{
    background: {T['accent']} !important;
    color: white !important;
}}

/* ── arquivos upados ── */
[data-testid="stFileUploader"] section ul li,
[data-testid="stFileUploader"] section ul li > div,
[data-testid="stFileUploader"] section > div > div {{
    background: {T['file_bg']} !important;
    border: 1px solid {T['file_border']} !important;
    border-radius: 8px !important;
    color: {T['file_text']} !important;
}}
[data-testid="stFileUploader"] section ul li span,
[data-testid="stFileUploader"] section ul li small,
[data-testid="stFileUploader"] section ul li p {{
    color: {T['file_text']} !important;
}}

/* ── botão primário (Azul Pará) ── */
.stButton > button[kind="primary"] {{
    background: {T['accent']} !important;
    color: #fff !important;
    border: none !important;
    border-radius: 8px !important;
    font-size: 0.85rem !important;
    font-weight: 700 !important;
    letter-spacing: -0.01em;
    padding: 0.65rem 1.5rem !important;
    box-shadow: {SH_SM};
    transition: background {DUR}, box-shadow {DUR}, transform {DUR} {EASE};
}}
.stButton > button[kind="primary"]:hover {{
    background: {T['accent_hover']} !important;
    box-shadow: {SH_MD};
}}
.stButton > button[kind="primary"]:active {{
    background: {T['accent_active']} !important;
    transform: translateY(1px);
}}
.stButton > button[kind="primary"]:disabled {{
    background: {T['btn_disabled']} !important;
    color: {T['btn_dis_txt']} !important;
    box-shadow: none !important;
    transform: none !important;
    cursor: not-allowed !important;
}}

/* ── botão secundário ── */
.stButton > button[kind="secondary"] {{
    background: {T['card']} !important;
    color: {T['text_soft']} !important;
    border: 1px solid {T['border']} !important;
    border-radius: 8px !important;
    font-size: 0.82rem !important;
    font-weight: 600 !important;
    transition: background {DUR}, border-color {DUR};
}}
.stButton > button[kind="secondary"]:hover {{
    background: {T['bg']} !important;
    border-color: {T['accent']} !important;
}}

/* ── download ── */
.stDownloadButton > button {{
    background: {T['card']} !important;
    color: {T['accent']} !important;
    border: 1.5px solid {T['accent']} !important;
    border-radius: 8px !important;
    font-size: 0.82rem !important;
    font-weight: 700 !important;
    transition: background {DUR};
}}
.stDownloadButton > button:hover {{
    background: {T['accent_bg']} !important;
}}
.stDownloadButton > button[kind="primary"] {{
    background: {T['accent']} !important;
    color: #fff !important;
    border: none !important;
    box-shadow: {SH_SM};
}}
.stDownloadButton > button[kind="primary"]:hover {{
    background: {T['accent_hover']} !important;
    box-shadow: {SH_MD};
}}

/* ── métricas ── */
[data-testid="metric-container"] {{
    background: {T['metric_bg']} !important;
    border: 1px solid {T['border']} !important;
    border-radius: 12px !important;
    padding: 1rem 1.2rem !important;
}}
[data-testid="metric-container"] label,
[data-testid="metric-container"] label p {{
    font-size: 0.68rem !important;
    font-weight: 700 !important;
    color: {T['text_muted']} !important;
    text-transform: uppercase !important;
    letter-spacing: 0.6px !important;
}}
[data-testid="metric-container"] [data-testid="stMetricValue"] div {{
    font-size: 1.7rem !important;
    font-weight: 700 !important;
    color: {T['text']} !important;
}}

/* ── alertas ── */
[data-testid="stAlert"] {{
    border-radius: 10px !important;
    font-size: 0.82rem !important;
    background: {T['accent_bg']} !important;
    border: 1px solid {T['border']} !important;
    color: {T['text']} !important;
}}

/* ── expander ── */
[data-testid="stExpander"] {{
    border: 1px solid {T['border']} !important;
    border-radius: 10px !important;
    background: {T['card']} !important;
}}
[data-testid="stExpander"] summary {{
    color: {T['text']} !important;
    font-size: 0.82rem !important;
}}

/* ── dataframe ── */
[data-testid="stDataFrame"] {{
    border-radius: 10px !important;
    border: 1px solid {T['border']} !important;
    overflow: hidden;
}}

/* ── console / terminal "hacker" (logs do bot) ── */
.bot-console {{
    background:
        repeating-linear-gradient(rgba(0,0,0,0) 0 2px, rgba(0,255,128,.018) 2px 3px),
        radial-gradient(120% 80% at 50% 0%, #0a1410 0%, #06090d 70%);
    border: 1px solid #163a25;
    border-radius: 8px;
    padding: 0.9rem 1rem 1.2rem;
    max-height: 340px;
    overflow-y: auto;
    font-family: 'Roboto Mono', ui-monospace, 'Consolas', monospace;
    font-size: 0.78rem;
    line-height: 1.6;
    white-space: pre-wrap;
    word-break: break-word;
    box-shadow: inset 0 0 70px rgba(0,255,120,.06), 0 0 0 1px rgba(0,255,120,.04);
}}
.bot-console div {{ margin: 0; }}
.bot-console::-webkit-scrollbar {{ width: 9px; }}
.bot-console::-webkit-scrollbar-thumb {{ background: #1d3a28; border-radius: 999px; }}
.bot-console .cursor {{ animation: termblink 1.1s steps(1) infinite; }}
@keyframes termblink {{ 50% {{ opacity: 0; }} }}
/* cores das linhas — especificidade alta p/ vencer a regra geral do tab-panel */
.stTabs [data-baseweb="tab-panel"] .bot-console,
.stTabs [data-baseweb="tab-panel"] .bot-console div {{
    color: #43e07a !important;                       /* verde fósforo (default) */
    text-shadow: 0 0 2px rgba(67,224,122,.35);
}}
.stTabs [data-baseweb="tab-panel"] .bot-console .log-ts {{
    color: #3fd0e8 !important; opacity: .9; text-shadow: none;
}}
.stTabs [data-baseweb="tab-panel"] .bot-console .log-ok    {{ color: #5cff9d !important; }}
.stTabs [data-baseweb="tab-panel"] .bot-console .log-erro  {{ color: #ff5f6e !important; text-shadow: 0 0 3px rgba(255,95,110,.5); }}
.stTabs [data-baseweb="tab-panel"] .bot-console .log-vazio {{ color: #ffc14d !important; }}
.stTabs [data-baseweb="tab-panel"] .bot-console .log-dim   {{ color: #4a6b57 !important; text-shadow: none; }}

/* ── texto geral dentro das abas ── */
.stTabs [data-baseweb="tab-panel"] p,
.stTabs [data-baseweb="tab-panel"] span,
.stTabs [data-baseweb="tab-panel"] div,
.stTabs [data-baseweb="tab-panel"] label {{
    color: {T['text']} !important;
}}
.stTabs [data-baseweb="tab-panel"] .stCaption,
.stTabs [data-baseweb="tab-panel"] .stCaption p,
.stTabs [data-baseweb="tab-panel"] small {{
    color: {T['text_soft']} !important;
}}
.stTabs [data-baseweb="tab-panel"] .section-title {{
    color: {T['text_muted']} !important;
}}
[data-testid="metric-container"] label p,
[data-testid="metric-container"] label span {{
    color: {T['text_muted']} !important;
}}
[data-testid="metric-container"] [data-testid="stMetricValue"],
[data-testid="metric-container"] [data-testid="stMetricValue"] div,
[data-testid="metric-container"] [data-testid="stMetricValue"] span {{
    color: {T['text']} !important;
}}

/* ── divider ── */
hr {{ border: none; border-top: 1px solid {T['border']}; margin: 1.2rem 0; }}
</style>
""", unsafe_allow_html=True)

# ── helpers ───────────────────────────────────────────────────────────────────
def info_base_of():
    """(nº de linhas, data de atualização) da base OF salva."""
    if not OF_PATH.exists():
        return 0, None
    mtime = datetime.fromtimestamp(OF_PATH.stat().st_mtime)
    with open(OF_PATH, encoding="utf-8", errors="replace") as f:
        n = sum(1 for _ in f) - 1
    return n, mtime

def carregar_of_salva():
    """Lê a base OF salva e devolve a lista de registros normalizados."""
    if not OF_PATH.exists():
        return []
    with open(OF_PATH, "rb") as f:
        return ler_of(f, "base_of.csv")

def ler_status_bot():
    """Lê o status.json escrito pelo bot. Devolve dict (ou None se ausente)."""
    if not STATUS_PATH.exists():
        return None
    try:
        with open(STATUS_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def resetar_ressarcimento():
    st.session_state.ress_etapa = "upload"
    st.session_state.ress_registros = []
    st.session_state.ress_header = []
    st.session_state.ress_obs = []
    st.session_state.ress_resultados = {}
    for p in (OBS_PATH, STATUS_PATH):
        try:
            p.unlink()
        except Exception:
            pass

def render_console(logs):
    """Renderiza o log do bot como um terminal, colorindo cada linha por resultado.

    Usa CLASSES CSS (não cor inline) porque a regra geral do tab-panel pinta
    div/span com `!important` e mataria estilos inline.
    """
    import html as _html
    linhas = []
    for ln in logs:
        esc = _html.escape(str(ln))
        up = esc.upper()
        # timestamp inicial (HH:MM:SS)
        if len(esc) >= 8 and esc[2] == ":" and esc[5] == ":":
            esc = f'<span class="log-ts">{esc[:8]}</span>{esc[8:]}'
        # classe da linha conforme o desfecho
        if "-> OK" in up or "→ OK" in up or "DESCRICAO OK" in up:
            cls = "log-ok"
        elif "ERRO" in up or "ERROR" in up or "TRACEBACK" in up or "FALHA" in up:
            cls = "log-erro"
        elif "VAZIO" in up:
            cls = "log-vazio"
        else:
            cls = ""
        linhas.append(f'<div class="{cls}">{esc}</div>')
    if not linhas:
        linhas.append('<div class="log-dim">Aguardando primeiras mensagens do bot…</div>')
    linhas.append('<div class="cursor">█</div>')  # cursor piscante
    st.markdown('<div class="bot-console">' + "".join(linhas) + "</div>",
                unsafe_allow_html=True)

# ── cabeçalho ─────────────────────────────────────────────────────────────────
_logo_img = f'<img src="{LOGO_URI}" class="app-logo" alt="SEDUC · Governo do Pará"/>' if LOGO_URI else ""
st.markdown(f"""
<div class="app-header">
    {_logo_img}
    <div class="app-divider"></div>
    <div>
        <h1>Diárias &amp; Ressarcimento</h1>
        <p>Secretaria de Estado de Educação do Pará</p>
    </div>
    <span class="app-header-badge">SEDUC-PA</span>
</div>
<div class="app-stripe"></div>
""", unsafe_allow_html=True)

# ── abas ──────────────────────────────────────────────────────────────────────
aba_proc, aba_ress, aba_cfg = st.tabs(["Processamento", "Ressarcimento", "Configurações"])


# ══════════════════════════════════════════════════════════════════════════════
# ABA 1 — PROCESSAMENTO
# ══════════════════════════════════════════════════════════════════════════════
with aba_proc:

    n_of, dt_of = info_base_of()
    of_rows = carregar_of_salva() if n_of else []
    meses = meses_da_of(of_rows) if of_rows else []

    if n_of == 0:
        st.warning("Base OF não encontrada. Envie a base na aba Configurações antes de processar.")
    else:
        st.markdown(
            f'<div class="base-info">Base OF ativa: <strong>{n_of:,} registros</strong>'
            f' — {len(meses)} mês(es) · atualizada em {dt_of.strftime("%d/%m/%Y às %H:%M")}</div>',
            unsafe_allow_html=True,
        )

    # seletor de mês (rótulo da competência)
    mes_alvo = None
    if meses:
        st.markdown('<p class="section-title">Competência</p>', unsafe_allow_html=True)
        st.caption("Define a competência (MÊS/ANO) do arquivo gerado.")
        mes_alvo = st.selectbox("mês", meses, index=len(meses) - 1, label_visibility="collapsed")

    st.markdown('<p class="section-title">Arquivos de diárias</p>', unsafe_allow_html=True)
    st.caption("Envie um ou mais relatórios de diárias (SIAFE). Formatos: CSV ou XLSX.")

    arquivos = st.file_uploader(
        "diárias",
        type=["xlsx", "xls", "csv"],
        accept_multiple_files=True,
        label_visibility="collapsed",
    )

    st.markdown("<br>", unsafe_allow_html=True)

    pode_processar = n_of > 0 and len(arquivos) > 0 and mes_alvo is not None

    if st.button("Processar", type="primary", use_container_width=True, disabled=not pode_processar):
        todos_registros = []
        with st.spinner("Lendo relatórios de diárias..."):
            for arq in arquivos:
                rows = ler_arquivo_diaria(arq, arq.name)
                todos_registros.extend(processar_diarias(rows))

        with st.spinner(f"Cruzando com a base OF (competência {mes_alvo})..."):
            vinculados, a_cadastrar, nao_encontradas = cruzar_of_hibrido(
                todos_registros, of_rows, mes_alvo)

        # guarda no estado p/ sobreviver aos reruns dos botões de download
        st.session_state.proc_result = {
            "mes": mes_alvo,
            "total": len(todos_registros),
            "vinculados": vinculados,
            "a_cadastrar": a_cadastrar,
            "nao_encontradas": nao_encontradas,
            "ts": datetime.now().strftime("%Y%m%d_%H%M"),
        }

    # ── resultado (renderizado fora do botão p/ os downloads persistirem) ───────
    res = st.session_state.proc_result
    if res:
        vinculados = res["vinculados"]
        a_cadastrar = res["a_cadastrar"]
        nao_encontradas = res["nao_encontradas"]
        por_ob = sum(1 for v in vinculados if v["ORIGEM"] == "OB")
        por_cpf = len(vinculados) - por_ob
        mes_arq = res["mes"].replace("/", "-")

        st.markdown("---")
        st.caption(f"Resultado da competência **{res['mes']}**")

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Lançamentos", res["total"])
        c2.metric("Vinculados", len(vinculados), help=f"{por_ob} por OB · {por_cpf} por CPF")
        c3.metric("A cadastrar na OF", len(a_cadastrar), help="ausentes da OF, com vínculo recuperado por CPF")
        c4.metric("Não encontradas", len(nao_encontradas), help="sem matrícula/vínculo — CPF também ausente da OF")

        st.markdown("<br>", unsafe_allow_html=True)

        # 1) CSV final — vinculados (OB + CPF inferido) → para o ERGON
        st.download_button(
            f"Baixar CSV de vinculados — {res['mes']} ({len(vinculados)} linhas)",
            data=gerar_csv_of_saida(vinculados),
            file_name=f"diarias_ergon_{mes_arq}_{res['ts']}.csv",
            mime="text/csv",
            use_container_width=True,
            type="primary",
            key="dl_vinc",
        )

        # 2) OBs a cadastrar na OF (vínculo provável por CPF) → time de cadastro
        if a_cadastrar:
            with st.expander(f"{len(a_cadastrar)} OB(s) a cadastrar na OF (com vínculo provável)"):
                st.dataframe(pd.DataFrame(a_cadastrar), use_container_width=True, hide_index=True)
            st.download_button(
                f"Baixar OBs a cadastrar na OF ({len(a_cadastrar)})",
                data=gerar_csv_of_cadastro(a_cadastrar),
                file_name=f"obs_a_cadastrar_OF_{mes_arq}_{res['ts']}.csv",
                mime="text/csv",
                use_container_width=True,
                key="dl_cad",
            )

        # 3) OBs NÃO encontradas (sem matrícula/vínculo/CPF na OF) → investigação
        if nao_encontradas:
            with st.expander(f"⚠️ {len(nao_encontradas)} OB(s) não encontradas "
                             f"(sem matrícula/vínculo — CPF ausente da OF)"):
                st.dataframe(pd.DataFrame(nao_encontradas), use_container_width=True, hide_index=True)
            st.download_button(
                f"Baixar OBs não encontradas ({len(nao_encontradas)})",
                data=gerar_csv_of_nao_encontradas(nao_encontradas),
                file_name=f"obs_nao_encontradas_{mes_arq}_{res['ts']}.csv",
                mime="text/csv",
                use_container_width=True,
                key="dl_nao",
            )


# ══════════════════════════════════════════════════════════════════════════════
# ABA 2 — RESSARCIMENTO
# ══════════════════════════════════════════════════════════════════════════════
with aba_ress:

    if not BOT_DISPONIVEL:
        st.warning(
            "⚠️ Esta instância não tem o bot SIAFE disponível (Chrome + chromedriver). "
            "O upload e a revisão manual funcionam normalmente, mas a captura automática "
            "de descrições só está disponível na versão **local** instalada no PC. "
            "Use a versão local para o trabalho mensal de ressarcimento."
        )

    etapa = st.session_state.ress_etapa

    # ── barra de etapas ────────────────────────────────────────────────────────
    nomes_etapas = {
        "upload":      "1 · Upload",
        "credenciais": "2 · SIAFE",
        "aguardando":  "3 · Bot",
        "revisao":     "4 · Revisão",
    }
    st.markdown(
        f'<p class="section-title">Ressarcimento de diárias &nbsp;—&nbsp; '
        f'etapa {nomes_etapas.get(etapa, etapa)}</p>',
        unsafe_allow_html=True,
    )

    if etapa != "upload":
        if st.button("↺ Recomeçar", key="ress_reset", type="secondary"):
            resetar_ressarcimento()
            st.rerun()

    # ───────────────────────────────────────────────────────────────────────────
    # ETAPA 1 — UPLOAD
    # ───────────────────────────────────────────────────────────────────────────
    if etapa == "upload":
        st.caption("Envie o relatório de ressarcimento exportado do SIAFE (XLSX ou CSV).")

        arq_ress = st.file_uploader(
            "relatório de ressarcimento",
            type=["xlsx", "xls", "csv"],
            label_visibility="collapsed",
            key="upload_ressarcimento",
        )

        if arq_ress is not None:
            try:
                registros, header = ler_ressarcimento_xlsx(arq_ress, arq_ress.name)
            except Exception as e:
                st.error(f"Erro ao ler o arquivo: {e}")
                registros, header = [], []

            if not registros:
                st.warning("Nenhuma OB válida encontrada no arquivo.")
            else:
                obs = obs_unicas(registros)
                st.success(f"{len(registros)} lançamentos · {len(obs)} OBs distintas encontradas.")

                df_prev = pd.DataFrame([{
                    "OB": r["ob"], "CREDOR": r["nome"],
                    "SITUAÇÃO": r["situacao"], "DATA": r["data"], "VALOR": r["valor"],
                } for r in registros])
                st.dataframe(df_prev, use_container_width=True, hide_index=True, height=260)

                if st.button("Avançar →", type="primary", use_container_width=True):
                    st.session_state.ress_registros = registros
                    st.session_state.ress_header = header
                    st.session_state.ress_obs = obs
                    st.session_state.ress_etapa = "credenciais"
                    st.rerun()

    # ───────────────────────────────────────────────────────────────────────────
    # ETAPA 2 — CREDENCIAIS
    # ───────────────────────────────────────────────────────────────────────────
    elif etapa == "credenciais":
        n_obs = len(st.session_state.ress_obs)
        st.markdown(
            f'<div class="base-info">{n_obs} OBs serão consultadas no SIAFE.</div>',
            unsafe_allow_html=True,
        )
        st.caption(
            "Informe suas credenciais do SIAFE. Elas são usadas apenas para esta "
            "execução e **nunca são gravadas em disco**."
        )

        siafe_user = st.text_input("Usuário SIAFE", key="ress_user")
        siafe_pass = st.text_input("Senha SIAFE", type="password", key="ress_pass")

        pode_iniciar = bool(siafe_user) and bool(siafe_pass) and BOT_DISPONIVEL
        if not BOT_DISPONIVEL:
            st.info("Bot indisponível nesta instância — use a versão local no PC.")
        if st.button("Iniciar bot", type="primary", use_container_width=True,
                     disabled=not pode_iniciar):
            try:
                # grava a lista de OBs para o bot consumir
                with open(OBS_PATH, "w", encoding="utf-8") as f:
                    json.dump(st.session_state.ress_obs, f, ensure_ascii=False)
                # limpa status anterior
                if STATUS_PATH.exists():
                    STATUS_PATH.unlink()

                if not BOT_PATH.exists():
                    st.error(f"Bot não encontrado em: {BOT_PATH}")
                else:
                    env = dict(os.environ)
                    env["SIAFE_USER"] = siafe_user
                    env["SIAFE_PASS"] = siafe_pass
                    subprocess.Popen(
                        [sys.executable, str(BOT_PATH), str(OBS_PATH), str(STATUS_PATH)],
                        env=env,
                        cwd=str(BOT_PATH.parent),
                    )
                    st.session_state.ress_etapa = "aguardando"
                    st.rerun()
            except Exception as e:
                st.error(f"Erro ao iniciar o bot: {e}")

    # ───────────────────────────────────────────────────────────────────────────
    # ETAPA 3 — AGUARDANDO O BOT
    # ───────────────────────────────────────────────────────────────────────────
    elif etapa == "aguardando":
        status = ler_status_bot()

        if status is None:
            st.info("Aguardando o bot iniciar... O Chrome abrirá em instantes.")
        else:
            estado = status.get("state", "")
            total = status.get("total", 0)
            proc = status.get("processed", 0)
            msg = status.get("message", "")

            mapa_estado = {
                "starting":    "Iniciando…",
                "logging_in":  "Fazendo login no SIAFE…",
                "navigating":  "Navegando até a consulta de OB…",
                "processing":  "Consultando OBs…",
                "done":        "Concluído!",
                "error":       "Erro na execução.",
            }
            st.markdown(
                f'<div class="base-info">Status: <strong>'
                f'{mapa_estado.get(estado, estado)}</strong></div>',
                unsafe_allow_html=True,
            )

            if total:
                st.progress(min(proc / total, 1.0), text=f"{proc} / {total} OBs")

            if estado == "error":
                st.error(f"O bot encontrou um problema: {msg}")
                if st.button("Voltar às credenciais", type="secondary"):
                    st.session_state.ress_etapa = "credenciais"
                    st.rerun()

        # ── painel de console (log ao vivo) ────────────────────────────────────
        st.markdown('<p class="section-title">Console</p>', unsafe_allow_html=True)
        render_console((status or {}).get("logs", []))

        estado_atual = (status or {}).get("state", "")
        em_andamento = estado_atual not in ("done", "error")

        c1, c2 = st.columns(2)
        with c1:
            if st.button("Atualizar status", use_container_width=True):
                st.rerun()
        with c2:
            bot_concluiu = estado_atual == "done"
            if st.button("Carregar resultados →", type="primary",
                         use_container_width=True, disabled=not bot_concluiu):
                resultados = {
                    item["ob"]: item.get("descricao", "")
                    for item in status.get("resultados", [])
                }
                st.session_state.ress_resultados = resultados
                st.session_state.ress_etapa = "revisao"
                st.rerun()

        # auto-atualização do console enquanto o bot está em execução
        if em_andamento:
            st.caption("Atualizando automaticamente a cada 2s…")
            time.sleep(2)
            st.rerun()

    # ───────────────────────────────────────────────────────────────────────────
    # ETAPA 4 — REVISÃO
    # ───────────────────────────────────────────────────────────────────────────
    elif etapa == "revisao":
        registros = st.session_state.ress_registros
        resultados = st.session_state.ress_resultados

        st.caption(
            "Revise as descrições capturadas. Preencha manualmente as que faltam e "
            "confirme quais lançamentos são, de fato, diárias."
        )

        # uma linha de revisão por OB distinta
        linhas = []
        info_por_ob = {}
        for reg in registros:
            info_por_ob.setdefault(reg["ob"], reg)
        for ob in st.session_state.ress_obs:
            reg = info_por_ob[ob]
            desc = resultados.get(ob, "")
            status_rev = classificar_descricao(desc)
            icone = {"ok": "✅", "verificar": "⚠️", "manual": "❌"}[status_rev]
            linhas.append({
                "STATUS": icone,
                "OB": ob,
                "CREDOR": reg["nome"],
                "SITUAÇÃO": reg["situacao"],
                "VALOR": reg["valor"],
                "DESCRIÇÃO": desc,
                "É DIÁRIA?": (status_rev == "ok"),
            })

        df_rev = pd.DataFrame(linhas)

        st.markdown(
            '<div class="base-info">✅ capturada &nbsp;·&nbsp; '
            '⚠️ sem a palavra "DIÁRIA" (confirme no checkbox) &nbsp;·&nbsp; '
            '❌ não capturada (preencha a descrição)</div>',
            unsafe_allow_html=True,
        )

        editado = st.data_editor(
            df_rev,
            use_container_width=True,
            hide_index=True,
            height=420,
            key="ress_editor",
            column_config={
                "STATUS":   st.column_config.TextColumn("•", width="small", disabled=True),
                "OB":       st.column_config.TextColumn("OB", disabled=True),
                "CREDOR":   st.column_config.TextColumn("Credor", disabled=True),
                "SITUAÇÃO": st.column_config.TextColumn("Situação", disabled=True),
                "VALOR":    st.column_config.TextColumn("Valor", disabled=True),
                "DESCRIÇÃO": st.column_config.TextColumn("Descrição", width="large"),
                "É DIÁRIA?": st.column_config.CheckboxColumn("É diária?"),
            },
        )

        # validação: nenhuma descrição pode estar vazia
        vazias = [
            r["OB"] for _, r in editado.iterrows()
            if not str(r["DESCRIÇÃO"]).strip()
        ]
        ress_marcadas = sum(1 for _, r in editado.iterrows() if r["É DIÁRIA?"])

        st.markdown("---")
        c1, c2, c3 = st.columns(3)
        c1.metric("OBs", len(editado))
        c2.metric("Descrições pendentes", len(vazias))
        c3.metric("Marcadas como diária", ress_marcadas)

        if vazias:
            st.error(
                f"Preencha a descrição das seguintes OBs antes de continuar: "
                f"{', '.join(vazias)}"
            )

        if st.button("Confirmar e gerar relatório", type="primary",
                     use_container_width=True, disabled=bool(vazias)):
            decisoes = {
                r["OB"]: {
                    "descricao": str(r["DESCRIÇÃO"]).strip(),
                    "is_diaria": bool(r["É DIÁRIA?"]),
                }
                for _, r in editado.iterrows()
            }
            mantidos, removidos = filtrar_ressarcimento(registros, decisoes)

            st.success(
                f"Relatório gerado: {len(mantidos)} lançamentos mantidos, "
                f"{len(removidos)} removidos (anulados, valor negativo ou não-diária)."
            )

            if removidos:
                with st.expander(f"{len(removidos)} lançamentos removidos"):
                    st.dataframe(
                        pd.DataFrame([{
                            "OB": r["ob"], "CREDOR": r["nome"],
                            "SITUAÇÃO": r["situacao"], "MOTIVO": r["motivo_remocao"],
                        } for r in removidos]),
                        use_container_width=True, hide_index=True,
                    )

            xlsx_bytes = gerar_xlsx_ressarcimento(mantidos, st.session_state.ress_header)
            ts = datetime.now().strftime("%Y%m%d_%H%M")
            st.download_button(
                "Baixar relatório de ressarcimento",
                data=xlsx_bytes,
                file_name=f"ressarcimento_filtrado_{ts}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
                type="primary",
            )
            st.caption(
                "Leve este arquivo para a aba **Processamento** e envie-o junto com "
                "os demais relatórios de diárias."
            )


# ══════════════════════════════════════════════════════════════════════════════
# ABA 3 — CONFIGURAÇÕES
# ══════════════════════════════════════════════════════════════════════════════
with aba_cfg:

    n_of, dt_of = info_base_of()
    of_rows = carregar_of_salva() if n_of else []
    meses = meses_da_of(of_rows) if of_rows else []

    st.markdown('<p class="section-title">Base OF (pagamentos)</p>', unsafe_allow_html=True)
    st.caption("Amarra cada OB à matrícula e vínculo corretos. Substitui a folha de pagamento.")

    if n_of == 0:
        st.warning("Nenhuma base OF carregada.")
    else:
        col1, col2, col3 = st.columns(3)
        col1.metric("Registros na OF", f"{n_of:,}")
        col2.metric("Meses cobertos", len(meses))
        col3.metric("Última atualização", dt_of.strftime("%d/%m/%Y"))
        if meses:
            st.caption("Meses disponíveis: " + " · ".join(meses))

    st.markdown("---")

    st.markdown('<p class="section-title">Atualizar base OF</p>', unsafe_allow_html=True)
    st.caption("Substitui a base atual. Envie o export mais recente da OF (PRDs_OBs).")

    novo_arquivo = st.file_uploader(
        "Nova base OF",
        type=["xlsx", "xls", "csv"],
        key="upload_of",
        label_visibility="collapsed",
    )

    # exibe mensagem persistente após rerun
    if st.session_state.msg_base:
        tipo, texto = st.session_state.msg_base
        if tipo == "success":
            st.success(texto)
        else:
            st.error(texto)
        st.session_state.msg_base = None

    if novo_arquivo:
        st.caption(f"Arquivo selecionado: {novo_arquivo.name}")
        if st.button("Salvar nova base OF", type="primary"):
            with st.spinner("Processando..."):
                try:
                    registros_of = ler_of(novo_arquivo, novo_arquivo.name)
                    if len(registros_of) == 0:
                        st.session_state.msg_base = (
                            "error",
                            "Nenhum registro válido encontrado. Confira se o arquivo tem a coluna 'num_ordem_bancaria'.",
                        )
                    else:
                        with open(OF_PATH, "wb") as f:
                            f.write(of_para_csv(registros_of))
                        n_meses = len(meses_da_of(registros_of))
                        st.session_state.msg_base = (
                            "success",
                            f"Base OF atualizada — {len(registros_of):,} registros, {n_meses} mês(es).",
                        )
                    st.rerun()
                except Exception as e:
                    st.session_state.msg_base = ("error", f"Erro ao processar o arquivo: {e}")
                    st.rerun()
