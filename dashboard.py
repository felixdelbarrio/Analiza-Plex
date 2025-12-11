import os
import warnings

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from backend.report_loader import load_reports
from backend.summary import compute_summary
from frontend.components import render_modal
from frontend.data_utils import format_count_size
from frontend.tabs import advanced, all_movies, candidates, charts, delete, metadata

# ----------------------------------------------------
# Warnings — silenciar SettingWithCopyWarning (st_aggrid/pandas)
# ----------------------------------------------------
warnings.filterwarnings(
    "ignore",
    message=".*A value is trying to be set on a copy of a slice from a DataFrame.*",
    category=pd.errors.SettingWithCopyWarning,
)
warnings.simplefilter("ignore", pd.errors.SettingWithCopyWarning)

# ----------------------------------------------------
# Carga de .env
# ----------------------------------------------------
load_dotenv()

OUTPUT_PREFIX = os.getenv("OUTPUT_PREFIX", "report")
DELETE_DRY_RUN = os.getenv("DELETE_DRY_RUN", "true").lower() == "true"
DELETE_REQUIRE_CONFIRM = os.getenv("DELETE_REQUIRE_CONFIRM", "true").lower() == "true"

ALL_CSV = f"{OUTPUT_PREFIX}_all.csv"
FILTERED_CSV = f"{OUTPUT_PREFIX}_filtered.csv"

METADATA_OUTPUT_PREFIX = os.getenv("METADATA_OUTPUT_PREFIX", "metadata_fix")
METADATA_SUGG_CSV = f"{METADATA_OUTPUT_PREFIX}_suggestions.csv"

# ----------------------------------------------------
# Estado global del modal
# ----------------------------------------------------
if "modal_open" not in st.session_state:
    st.session_state["modal_open"] = False
if "modal_row" not in st.session_state:
    st.session_state["modal_row"] = None

# ----------------------------------------------------
# Página principal
# ----------------------------------------------------
st.set_page_config(page_title="Plex Movies Cleaner", layout="wide")

st.markdown(
    """
    <style>
    header[data-testid="stHeader"],
    .stAppHeader,
    div[class*="stAppHeader"],
    div[data-testid="stToolbar"],
    div[data-testid="stCommandBar"] {
        display: none !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

if not st.session_state.get("modal_open"):
    st.title("🎬 Plex Movies Cleaner — Dashboard")

# Vista modal de detalle
render_modal()
if st.session_state.get("modal_open"):
    st.stop()

# ----------------------------------------------------
# Carga de datos (ahora usando backend.report_loader)
# ----------------------------------------------------
if not os.path.exists(ALL_CSV):
    st.error("No se encuentra report_all.csv. Ejecuta analiza_plex.py primero.")
    st.stop()

df_all, df_filtered = load_reports(ALL_CSV, FILTERED_CSV)

# ----------------------------------------------------
# Resumen general (backend.summary)
# ----------------------------------------------------
st.subheader("Resumen general")

summary = compute_summary(df_all)

# 5 métricas: Total, KEEP, DELETE, MAYBE, IMDb medio catálogo analizado
col1, col2, col3, col4, col5 = st.columns(5)

col1.metric(
    "Películas",
    format_count_size(summary["total_count"], summary["total_size_gb"]),
)
col2.metric(
    "KEEP",
    format_count_size(summary["keep_count"], summary["keep_size_gb"]),
)
col3.metric(
    "DELETE",
    format_count_size(
        summary.get("delete_count", 0),
        summary.get("delete_size_gb"),
    ),
)
col4.metric(
    "MAYBE",
    format_count_size(
        summary.get("maybe_count", 0),
        summary.get("maybe_size_gb"),
    ),
)

# Medias IMDb
imdb_mean_df = summary.get("imdb_mean_df")
imdb_mean_cache = summary.get("imdb_mean_cache")

if imdb_mean_df is not None and not pd.isna(imdb_mean_df):
    col5.metric("IMDb medio (analizado)", f"{imdb_mean_df:.2f}")
else:
    col5.metric("IMDb medio (analizado)", "N/A")

# Caption con la media global basada en omdb_cache / bayes
if imdb_mean_cache is not None and not pd.isna(imdb_mean_cache):
    st.caption(
        f"IMDb medio global (omdb_cache / bayes): **{imdb_mean_cache:.2f}**"
    )

st.markdown("---")

# ----------------------------------------------------
# Pestañas
# ----------------------------------------------------
tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(
    [
        "📚 Todas",
        "⚠️ Candidatas",
        "🔎 Búsqueda avanzada",
        "🧹 Borrado",
        "📊 Gráficos",
        "🧠 Metadata",
    ]
)

with tab1:
    all_movies.render(df_all)

with tab2:
    candidates.render(df_all, df_filtered)

with tab3:
    advanced.render(df_all)

with tab4:
    delete.render(df_filtered, DELETE_DRY_RUN, DELETE_REQUIRE_CONFIRM)

with tab5:
    charts.render(df_all)

with tab6:
    metadata.render(METADATA_SUGG_CSV)