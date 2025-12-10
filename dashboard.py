import os
from pathlib import Path

import pandas as pd
import streamlit as st
import altair as alt
from dotenv import load_dotenv
from st_aggrid import AgGrid, GridOptionsBuilder, GridUpdateMode

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
# Función de borrado
# ----------------------------------------------------
def delete_files_from_rows(rows: pd.DataFrame):
    num_ok = 0
    num_error = 0
    logs = []

    for _, row in rows.iterrows():
        file_path = row.get("file")
        title = row.get("title")

        if not file_path:
            logs.append(f"[SKIP] {title} -> sin ruta de archivo")
            continue

        p = Path(str(file_path))
        if not p.exists():
            logs.append(f"[SKIP] {title} -> archivo no existe: {file_path}")
            continue

        if DELETE_DRY_RUN:
            logs.append(f"[DRY RUN] {title} -> NO se borra: {file_path}")
            continue

        try:
            os.remove(p)
            logs.append(f"[OK] BORRADO {title} -> {file_path}")
            num_ok += 1
        except Exception as e:
            logs.append(f"[ERROR] {title}: {e}")
            num_error += 1

    return num_ok, num_error, logs


# ----------------------------------------------------
# Helpers de presentación / datos
# ----------------------------------------------------
def clean_base_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """Quitamos columnas claramente redundantes en el dashboard."""
    cols = [c for c in df.columns if c != "thumb"]
    return df[cols]


def aggrid_with_row_click(df: pd.DataFrame, key_suffix: str):
    """
    AgGrid → selección por click → devuelve dict con todos los valores de la fila.
    El grid solo muestra las columnas mínimas operativas,
    el resto quedan ocultas pero disponibles para el detalle.
    """
    if df.empty:
        st.info("No hay datos para mostrar.")
        return None

    # Columnas visibles y su orden
    desired_order = [
        "title",
        "year",
        "library",
        "imdb_rating",
        "imdb_votes",
        "rt_score",
        "plex_rating",
        "decision",
        "reason",
    ]
    visible_cols = [c for c in desired_order if c in df.columns]

    # Reordenamos df: visibles primero, luego resto
    ordered_cols = visible_cols + [c for c in df.columns if c not in visible_cols]
    df = df[ordered_cols]

    gb = GridOptionsBuilder.from_dataframe(df)
    gb.configure_selection(selection_mode="single", use_checkbox=False)
    gb.configure_grid_options(domLayout="normal")

    # Ocultar las no visibles (incluida file, poster_url, etc.)
    for col in df.columns:
        if col not in visible_cols:
            gb.configure_column(col, hide=True)

    grid_options = gb.build()

    grid_response = AgGrid(
        df,
        gridOptions=grid_options,
        update_mode=GridUpdateMode.SELECTION_CHANGED,
        enable_enterprise_modules=False,
        fit_columns_on_grid_load=True,
        height=520,
        key=f"aggrid_{key_suffix}",
    )

    selected_raw = grid_response.get("selected_rows", None)

    if selected_raw is None:
        return None

    if isinstance(selected_raw, pd.DataFrame):
        selected_raw = selected_raw.to_dict(orient="records")

    if not isinstance(selected_raw, list):
        selected_raw = list(selected_raw)

    if len(selected_raw) == 0:
        return None

    partial = selected_raw[0]
    final_row = {col: partial.get(col, None) for col in df.columns}

    return final_row


def render_detail_card(row: dict, show_modal_button=True):
    """
    Panel lateral / ficha de detalle tipo Plex.
    """
    if row is None:
        st.info("Haz click en una fila para ver su detalle.")
        return

    def safe(*keys):
        for k in keys:
            if k is None:
                continue
            v = row.get(k, None)
            if v is not None and str(v).strip() not in ("", "nan", "None"):
                return v
        return None

    title = safe("title") or "(sin título)"
    year = safe("year")
    library = safe("library")
    decision = safe("decision")
    reason = safe("reason")
    imdb_rating = safe("imdb_rating")
    rt_score = safe("rt_score")
    imdb_votes = safe("imdb_votes")
    imdb_id = safe("imdb_id")
    poster_url = safe("poster_url")
    file_path = safe("file")
    file_size = safe("file_size")
    rating_key = safe("ratingKey")
    trailer_url = safe("trailer_url")

    # Campos OMDb extra
    rated = safe("Rated", "rated")
    released = safe("Released", "released")
    runtime = safe("Runtime", "runtime")
    genre = safe("Genre", "genre")
    director = safe("Director", "director")
    writer = safe("Writer", "writer")
    actors = safe("Actors", "actors")
    language = safe("Language", "language")
    country = safe("Country", "country")
    awards = safe("Awards", "awards")

    # Sinopsis: ahora comprobamos también "Plot" con mayúscula
    plot = (
        safe("plot", "Plot")
        or safe("summary")
        or safe("overview")
        or safe("description")
    )

    col_left, col_right = st.columns([1, 2])

    # ------------- POSTER PANEL -------------
    with col_left:
        if poster_url and str(poster_url).strip() and str(poster_url).lower() not in ("nan", "none"):
            st.image(poster_url, width=280)
        else:
            st.write("📷 Sin póster")

        if imdb_id:
            imdb_url = f"https://www.imdb.com/title/{imdb_id}"
            st.markdown(f"[🎬 Ver en IMDb]({imdb_url})")

        plex_base = os.getenv("PLEX_WEB_BASEURL", "")
        if plex_base and rating_key:
            plex_url = f"{plex_base}/web/index.html#!/server/library/metadata/{rating_key}"
            st.markdown(f"[📺 Ver en Plex Web]({plex_url})")

        if show_modal_button:
            if st.button("🪟 Abrir en ventana"):
                st.session_state["modal_row"] = row
                st.session_state["modal_open"] = True
                st.rerun()

    # ------------- DETAIL PANEL -------------
    with col_right:
        header = title
        try:
            if pd.notna(year):
                header += f" ({int(year)})"
        except Exception:
            pass

        st.markdown(f"### {header}")
        st.write(f"**Biblioteca:** {library}")
        st.write(f"**Decisión:** `{decision}` — {reason}")

        # Métricas principales
        m1, m2, m3 = st.columns(3)
        m1.metric("IMDb", f"{imdb_rating}" if pd.notna(imdb_rating) else "N/A")
        m2.metric("RT", f"{rt_score}%" if pd.notna(rt_score) else "N/A")
        m3.metric("Votos", int(imdb_votes) if pd.notna(imdb_votes) else "N/A")

        # Bloque OMDb info básica
        st.markdown("---")
        st.write("#### Información OMDb")

        cols_basic = st.columns(4)
        with cols_basic[0]:
            if rated:
                st.write(f"**Rated:** {rated}")
        with cols_basic[1]:
            if released:
                st.write(f"**Estreno:** {released}")
        with cols_basic[2]:
            if runtime:
                st.write(f"**Duración:** {runtime}")
        with cols_basic[3]:
            if genre:
                st.write(f"**Género:** {genre}")

        # Créditos
        st.write("")
        cols_credits = st.columns(3)
        with cols_credits[0]:
            if director:
                st.write(f"**Director:** {director}")
        with cols_credits[1]:
            if writer:
                st.write(f"**Guion:** {writer}")
        with cols_credits[2]:
            if actors:
                st.write(f"**Reparto:** {actors}")

        # Producción / premios
        st.write("")
        cols_prod = st.columns(3)
        with cols_prod[0]:
            if language:
                st.write(f"**Idioma(s):** {language}")
        with cols_prod[1]:
            if country:
                st.write(f"**País:** {country}")
        with cols_prod[2]:
            if awards:
                st.write(f"**Premios:** {awards}")

        # Sinopsis
        if plot and str(plot).strip():
            st.markdown("---")
            st.write("#### Sinopsis")
            st.write(str(plot))

        # Archivo
        st.markdown("---")
        st.write("#### Archivo")
        if file_path:
            st.code(file_path, language="bash")
        if pd.notna(file_size):
            try:
                gb = float(file_size) / (1024 ** 3)
                st.write(f"**Tamaño:** {gb:.2f} GB")
            except Exception:
                pass

        # Tráiler
        if trailer_url and str(trailer_url).strip() and str(trailer_url).lower() not in ("nan", "none"):
            st.markdown("#### 🎞 Tráiler")
            st.video(trailer_url)

    # JSON completo
    with st.expander("Ver JSON completo"):
        st.json(row)


def render_modal():
    """
    Ventana modal superpuesta — usa sesión como estado.
    ❗ Sin overlay oscurecedor: solo una caja flotante coherente con el tema.
    """
    if not st.session_state["modal_open"]:
        return

    row = st.session_state["modal_row"]
    if row is None:
        return

    # Solo la caja: nada de overlay oscuro para que el brillo sea idéntico al resto
    st.markdown(
        """
        <style>
        :root {
            --main-bg: var(--background-color, #0e1117);
            --sec-bg: var(--secondary-background-color, #262730);
            --txt: var(--text-color, #fafafa);
        }

        .modal-box {
            position: fixed;
            top: 5%;
            left: 50%;
            transform: translateX(-50%);
            width: 80%;
            max-height: 85%;
            overflow-y: auto;
            background: var(--sec-bg);
            border-radius: 14px;
            padding: 24px 28px;
            z-index: 10001;
            box-shadow: 0 24px 48px rgba(0,0,0,0.7);
            border: 1px solid rgba(255,255,255,0.12);
            color: var(--txt);
        }

        .modal-box * {
            color: var(--txt) !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    st.markdown('<div class="modal-box">', unsafe_allow_html=True)

    c1, c2 = st.columns([10, 1])
    with c1:
        st.markdown("### 🔍 Detalle ampliado")
    with c2:
        if st.button("✖", key="close_modal"):
            st.session_state["modal_open"] = False
            st.session_state["modal_row"] = None
            st.rerun()

    render_detail_card(row, show_modal_button=False)

    st.markdown("</div>", unsafe_allow_html=True)


# ----------------------------------------------------
# Página principal
# ----------------------------------------------------
st.set_page_config(page_title="Plex Movies Cleaner", layout="wide")
st.title("🎬 Plex Movies Cleaner — Dashboard")

# Modal (si está activo)
render_modal()

if not os.path.exists(ALL_CSV):
    st.error("No se encuentra report_all.csv. Ejecuta analiza_plex.py primero.")
    st.stop()

df_all = pd.read_csv(ALL_CSV)
df_filtered = pd.read_csv(FILTERED_CSV) if os.path.exists(FILTERED_CSV) else None

# Tipos numéricos
num_cols = ["imdb_rating", "rt_score", "imdb_votes", "year", "plex_rating", "file_size"]
for c in num_cols:
    if c in df_all.columns:
        df_all[c] = pd.to_numeric(df_all[c], errors="coerce")

for col in ["poster_url", "trailer_url"]:
    if col in df_all.columns:
        df_all[col] = df_all[col].astype(str)

df_all = clean_base_dataframe(df_all)
if df_filtered is not None:
    df_filtered = clean_base_dataframe(df_filtered)

# ----------------------------------------------------
# Resumen general
# ----------------------------------------------------
st.subheader("Resumen general")

col1, col2, col3 = st.columns(3)
col1.metric("Películas", len(df_all))
col2.metric("KEEP", int((df_all["decision"] == "KEEP").sum()))
col3.metric("DELETE/MAYBE", int(df_all["decision"].isin(["DELETE", "MAYBE"]).sum()))

st.markdown("---")

# ----------------------------------------------------
# Pestañas
# ----------------------------------------------------
tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(
    ["📚 Todas", "⚠️ Candidatas", "🔎 Búsqueda avanzada", "🧹 Borrado", "📊 Gráficos", "🧠 Metadata"]
)

# ----------------------------------------------------
# Tab 1: Todas
# ----------------------------------------------------
with tab1:
    st.write("### Todas las películas")
    df_view = df_all.copy()
    col_grid, col_detail = st.columns([2, 1])
    with col_grid:
        selected_row = aggrid_with_row_click(df_view, "all")
    with col_detail:
        render_detail_card(selected_row)

# ----------------------------------------------------
# Tab 2: Candidatas
# ----------------------------------------------------
with tab2:
    st.write("### Películas candidatas")
    if df_filtered is None:
        st.warning("No hay CSV filtrado")
    else:
        df_view = df_filtered.copy()
        colg, cold = st.columns([2, 1])
        with colg:
            selected_row2 = aggrid_with_row_click(df_view, "filtered")
        with cold:
            render_detail_card(selected_row2)

# ----------------------------------------------------
# Tab 3: Búsqueda avanzada
# ----------------------------------------------------
with tab3:
    st.write("### Búsqueda avanzada")
    title_query = st.text_input("Buscar título:")
    df_view = df_all.copy()
    if title_query:
        df_view = df_view[df_view["title"].str.contains(title_query, case=False, na=False)]
    colg3, cold3 = st.columns([2, 1])
    with colg3:
        selected_row3 = aggrid_with_row_click(df_view, "search")
    with cold3:
        render_detail_card(selected_row3)

# ----------------------------------------------------
# Tab 4: Borrado
# ----------------------------------------------------
with tab4:
    st.write("### Borrado de archivos marcados como DELETE")
    if df_filtered is None:
        st.warning("No hay CSV filtrado")
    else:
        df_del = df_filtered[df_filtered["decision"] == "DELETE"]
        st.dataframe(df_del, use_container_width=True)
        if DELETE_REQUIRE_CONFIRM:
            confirm = st.text_input("Escribe BORRAR:")
            ok = confirm.strip().upper() == "BORRAR"
        else:
            ok = True
        if st.button("Borrar archivos"):
            if not ok:
                st.error("Debes escribir BORRAR")
            else:
                with st.spinner("Procesando..."):
                    num_ok, num_err, logs = delete_files_from_rows(df_del)
                st.success(f"Borrado completado. OK={num_ok}, Errores={num_err}")
                st.text_area("Log", "\n".join(logs))

# ----------------------------------------------------
# Tab 5: Gráficos (ejemplo sencillo)
# ----------------------------------------------------
with tab5:
    st.write("### Gráficos")
    if "imdb_rating" in df_all.columns:
        chart = (
            alt.Chart(df_all.dropna(subset=["imdb_rating"]))
            .mark_bar()
            .encode(
                x=alt.X("imdb_rating:Q", bin=alt.Bin(maxbins=20), title="IMDb"),
                y=alt.Y("count():Q", title="Nº pelis"),
            )
        )
        st.altair_chart(chart, use_container_width=True)

# ----------------------------------------------------
# Tab 6: Metadata
# ----------------------------------------------------
with tab6:
    st.write("### Sugerencias de metadata")
    if os.path.exists(METADATA_SUGG_CSV):
        df_meta = pd.read_csv(METADATA_SUGG_CSV)
        st.dataframe(df_meta, use_container_width=True)
    else:
        st.info(f"No se ha encontrado {METADATA_SUGG_CSV}")