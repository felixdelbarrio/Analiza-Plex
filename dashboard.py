import os
from pathlib import Path
import json
import re
from collections import Counter

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
# Helpers ligeros de datos (OMDb por fila, tamaños, décadas…)
# ----------------------------------------------------
def safe_json_loads_single(x):
    """Parsea JSON solo cuando se necesita (para una fila o subconjunto)."""
    if isinstance(x, str) and x.strip():
        try:
            return json.loads(x)
        except Exception:
            return None
    if isinstance(x, dict):
        return x
    return None


def add_derived_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Columnas derivadas baratas: tamaños, década…"""
    df = df.copy()

    # Tipos numéricos básicos
    for col in ["imdb_rating", "rt_score", "imdb_votes", "year", "plex_rating", "file_size"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # Tamaño en GB
    if "file_size" in df.columns:
        df["file_size_gb"] = df["file_size"].astype("float64") / (1024 ** 3)

    # Década
    if "year" in df.columns:
        df["decade"] = df["year"].dropna().astype("float64")
        df["decade"] = (df["decade"] // 10) * 10
        df["decade_label"] = df["decade"].apply(lambda x: f"{int(x)}s" if not pd.isna(x) else None)

    return df


def explode_genres_from_omdb_json(df: pd.DataFrame) -> pd.DataFrame:
    """
    Construye un DF exploded por género usando la columna omdb_json.
    Pensada solo para la vista de géneros (tab de gráficos) para no
    penalizar rendimiento en el resto del dashboard.
    """
    if "omdb_json" not in df.columns:
        return pd.DataFrame(columns=list(df.columns) + ["genre"])

    # Copia con índice limpio para evitar problemas de reindex
    df_g = df.copy().reset_index(drop=True)

    def extract_genre(raw):
        d = safe_json_loads_single(raw)
        if not isinstance(d, dict):
            return []
        g = d.get("Genre")
        if not g:
            return []
        return [x.strip() for x in str(g).split(",") if x.strip()]

    # Lista de géneros por fila
    df_g["genre_list"] = df_g["omdb_json"].apply(extract_genre)

    # Explode → una fila por género
    df_g = df_g.explode("genre_list").reset_index(drop=True)

    # Pasamos genre_list a genre
    df_g = df_g.rename(columns={"genre_list": "genre"})

    # Filtro con máscara simple para evitar el bug de reindex
    mask = df_g["genre"].notna() & (df_g["genre"] != "")
    df_g = df_g.loc[mask].copy()

    return df_g


def build_word_counts(df: pd.DataFrame, decisions: list) -> pd.DataFrame:
    df = df[df["decision"].isin(decisions)].copy()
    if df.empty:
        return pd.DataFrame(columns=["word", "decision", "count"])

    stopwords = set(
        [
            "the",
            "of",
            "la",
            "el",
            "de",
            "y",
            "a",
            "en",
            "los",
            "las",
            "un",
            "una",
            "and",
            "to",
            "for",
            "con",
            "del",
            "le",
            "les",
            "die",
            "der",
            "das",
        ]
    )

    rows = []
    for dec, sub in df.groupby("decision"):
        words = []
        for t in sub["title"].dropna().astype(str):
            t_clean = re.sub(r"[^\w\s]", " ", t, flags=re.UNICODE)
            for w in t_clean.split():
                w_norm = w.strip().lower()
                if len(w_norm) <= 2:
                    continue
                if w_norm in stopwords:
                    continue
                words.append(w_norm)

        counts = Counter(words)
        for w, c in counts.items():
            rows.append({"word": w, "decision": dec, "count": c})

    out = pd.DataFrame(rows)
    if out.empty:
        return out
    return out.sort_values("count", ascending=False)


# ----------------------------------------------------
# Paleta de colores por decisión
# ----------------------------------------------------
def decision_color(field: str = "decision"):
    """
    Colores fijos:
    - DELETE  → rojo
    - KEEP    → verde
    - MAYBE   → amarillo
    - UNKNOWN → gris
    """
    return alt.Color(
        f"{field}:N",
        title="Decisión",
        scale=alt.Scale(
            domain=["DELETE", "KEEP", "MAYBE", "UNKNOWN"],
            range=["#e53935", "#43a047", "#fbc02d", "#9e9e9e"],
        ),
    )


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

    # Columnas visibles y su orden (grid mínimo operativo)
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

    # Ocultar las no visibles (incluida file, poster_url, omdb_json, etc.)
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

    row = selected_raw[0]
    return row


def render_detail_card(row: dict, show_modal_button=True):
    """
    Panel lateral / ficha de detalle tipo Plex.
    Parseamos omdb_json SOLO para esta fila (si existe), no todo el DF.
    """
    if row is None:
        st.info("Haz click en una fila para ver su detalle.")
        return

    # Parseo puntual del JSON para la fila
    omdb_dict = None
    if "omdb_json" in row:
        omdb_dict = safe_json_loads_single(row.get("omdb_json"))

    def from_omdb(key):
        if omdb_dict and isinstance(omdb_dict, dict):
            return omdb_dict.get(key)
        return None

    # Campos básicos
    title = row.get("title", "¿Sin título?")
    year = row.get("year")
    library = row.get("library")
    decision = row.get("decision")
    reason = row.get("reason")
    imdb_rating = row.get("imdb_rating")
    imdb_votes = row.get("imdb_votes")
    rt_score = row.get("rt_score")
    plex_rating = row.get("plex_rating")
    poster_url = row.get("poster_url")
    file_path = row.get("file")
    file_size = row.get("file_size")
    trailer_url = row.get("trailer_url")
    rating_key = row.get("rating_key")
    imdb_id = row.get("imdb_id")

    rated = row.get("Rated") or from_omdb("Rated")
    released = row.get("Released") or from_omdb("Released")
    runtime = row.get("Runtime") or from_omdb("Runtime")
    genre = row.get("Genre") or from_omdb("Genre")
    director = row.get("Director") or from_omdb("Director")
    writer = row.get("Writer") or from_omdb("Writer")
    actors = row.get("Actors") or from_omdb("Actors")
    language = row.get("Language") or from_omdb("Language")
    country = row.get("Country") or from_omdb("Country")
    awards = row.get("Awards") or from_omdb("Awards")
    plot = row.get("Plot") or from_omdb("Plot")

    # Layout principal del panel
    col_left, col_right = st.columns([1, 2])

    # ------------- POSTER -------------
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
        full_row = dict(row)
        if omdb_dict is not None:
            full_row["_omdb_parsed"] = omdb_dict
        st.json(full_row)


def render_modal():
    """
    Vista de detalle ampliado (sin wrapper modal-box).
    """
    if not st.session_state["modal_open"]:
        return

    row = st.session_state["modal_row"]
    if row is None:
        return

    # Cabecera de la vista de detalle
    c1, c2 = st.columns([10, 1])
    with c1:
        st.markdown("### 🔍 Detalle ampliado")
    with c2:
        if st.button("✖", key="close_modal"):
            st.session_state["modal_open"] = False
            st.session_state["modal_row"] = None
            st.rerun()

    # Contenido de detalle
    render_detail_card(row, show_modal_button=False)


# ----------------------------------------------------
# Página principal
# ----------------------------------------------------
st.set_page_config(page_title="Plex Movies Cleaner", layout="wide")

# Ocultamos header / toolbar / command bar de Streamlit
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

# Título principal solo cuando NO hay modal abierto
if not st.session_state.get("modal_open"):
    st.title("🎬 Plex Movies Cleaner — Dashboard")

# Si hay "modal", mostramos solo la vista de detalle y paramos
render_modal()
if st.session_state.get("modal_open"):
    st.stop()

# ----------------------------------------------------
# Carga de datos
# ----------------------------------------------------
if not os.path.exists(ALL_CSV):
    st.error("No se encuentra report_all.csv. Ejecuta analiza_plex.py primero.")
    st.stop()

df_all = pd.read_csv(ALL_CSV)
df_filtered = pd.read_csv(FILTERED_CSV) if os.path.exists(FILTERED_CSV) else None

# Campos texto importantes
for col in ["poster_url", "trailer_url", "omdb_json"]:
    if col in df_all.columns:
        df_all[col] = df_all[col].astype(str)

# Columnas derivadas ligeras
df_all = add_derived_columns(df_all)

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
    st.write("### Candidatas a borrar (DELETE / MAYBE)")
    if df_filtered is None or df_filtered.empty:
        st.info("No hay CSV filtrado o está vacío.")
    else:
        df_view = df_filtered.copy()
        col_grid, col_detail = st.columns([2, 1])
        with col_grid:
            selected_row = aggrid_with_row_click(df_view, "filtered")
        with col_detail:
            render_detail_card(selected_row)

# ----------------------------------------------------
# Tab 3: Búsqueda avanzada
# ----------------------------------------------------
with tab3:
    st.write("### Búsqueda avanzada")

    df_view = df_all.copy()

    col_f1, col_f2, col_f3, col_f4 = st.columns(4)

    with col_f1:
        lib_filter = st.multiselect(
            "Biblioteca", sorted(df_view["library"].dropna().unique().tolist())
        )

    with col_f2:
        dec_filter = st.multiselect(
            "Decisión",
            ["DELETE", "MAYBE", "KEEP", "UNKNOWN"],
            default=["DELETE", "MAYBE", "KEEP", "UNKNOWN"],
        )

    with col_f3:
        min_imdb = st.slider("IMDb mínimo", 0.0, 10.0, 0.0, 0.1)

    with col_f4:
        min_votes = st.slider("IMDb votos mínimos", 0, 200000, 0, 1000)

    if lib_filter:
        df_view = df_view[df_view["library"].isin(lib_filter)]

    if dec_filter:
        df_view = df_view[df_view["decision"].isin(dec_filter)]

    df_view = df_view[
        (df_view["imdb_rating"].fillna(0) >= min_imdb)
        & (df_view["imdb_votes"].fillna(0) >= min_votes)
    ]

    st.write(f"Resultados: {len(df_view)} película(s)")

    col_grid, col_detail = st.columns([2, 1])
    with col_grid:
        selected_row = aggrid_with_row_click(df_view, "advanced")
    with col_detail:
        render_detail_card(selected_row)

# ----------------------------------------------------
# Tab 4: Borrado
# ----------------------------------------------------
with tab4:
    st.write("### Borrado controlado de archivos")

    if df_filtered is None or df_filtered.empty:
        st.info("No hay CSV filtrado. Ejecuta primero el análisis.")
    else:
        st.warning(
            "⚠️ Cuidado: aquí puedes borrar archivos físicamente.\n\n"
            f"- DELETE_DRY_RUN = `{DELETE_DRY_RUN}`\n"
            f"- DELETE_REQUIRE_CONFIRM = `{DELETE_REQUIRE_CONFIRM}`"
        )

        df_view = df_filtered.copy()

        st.write("Filtra las películas que quieras borrar y selecciónalas en la tabla:")

        col_f1, col_f2 = st.columns(2)

        with col_f1:
            lib_filter = st.multiselect(
                "Biblioteca", sorted(df_view["library"].dropna().unique().tolist())
            )
        with col_f2:
            dec_filter = st.multiselect(
                "Decisión", ["DELETE", "MAYBE"], default=["DELETE", "MAYBE"]
            )

        if lib_filter:
            df_view = df_view[df_view["library"].isin(lib_filter)]
        if dec_filter:
            df_view = df_view[df_view["decision"].isin(dec_filter)]

        gb = GridOptionsBuilder.from_dataframe(df_view)
        gb.configure_selection(selection_mode="multiple", use_checkbox=True)
        gb.configure_grid_options(domLayout="normal")
        grid_options = gb.build()

        grid_response = AgGrid(
            df_view,
            gridOptions=grid_options,
            update_mode=GridUpdateMode.SELECTION_CHANGED,
            enable_enterprise_modules=False,
            fit_columns_on_grid_load=True,
            height=500,
            key="aggrid_delete",
        )

        selected_rows = grid_response.get("selected_rows", None)
        if isinstance(selected_rows, pd.DataFrame):
            selected_rows = selected_rows.to_dict(orient="records")

        num_selected = len(selected_rows) if selected_rows else 0
        st.write(f"Películas seleccionadas: {num_selected}")

        if num_selected > 0:
            if DELETE_REQUIRE_CONFIRM:
                confirm = st.checkbox(
                    "Confirmo que quiero borrar físicamente los archivos seleccionados."
                )
            else:
                confirm = True

            if st.button("🗑️ Ejecutar borrado"):
                if not confirm:
                    st.warning("Marca la casilla de confirmación antes de borrar.")
                else:
                    df_sel = pd.DataFrame(selected_rows)
                    ok, err, logs = delete_files_from_rows(df_sel)

                    st.success(f"Borrado completado. OK={ok}, errores={err}")
                    st.text_area("Log de borrado", value="\n".join(logs), height=200)

# ----------------------------------------------------
# Tab 5: Gráficos
# ----------------------------------------------------
with tab5:
    st.write("### Gráficos")

    view = st.selectbox(
        "Vista",
        [
            "Distribución por decisión",
            "Rating IMDb por decisión",
            "Ratings IMDb vs RT",
            "Distribución por década",
            "Distribución por biblioteca",
            "Distribución por género (OMDb)",
            "Espacio ocupado por biblioteca/decisión",
            "Boxplot IMDb por biblioteca",
            "Ranking de directores",
            "Palabras más frecuentes en títulos DELETE/MAYBE",
        ],
    )

    df_g = df_all.copy()

    # 1) Distribución por decisión
    if view == "Distribución por decisión":
        if "decision" not in df_g.columns:
            st.info("No hay columna 'decision'.")
        else:
            agg = df_g.groupby("decision")["title"].count().reset_index()
            agg = agg.rename(columns={"title": "count"})

            chart = (
                alt.Chart(agg)
                .mark_bar()
                .encode(
                    x=alt.X("decision:N", title="Decisión"),
                    y=alt.Y("count:Q", title="Número de películas"),
                    color=decision_color("decision"),
                    tooltip=["decision", "count"],
                )
            )
            st.altair_chart(chart, use_container_width=True)

    # 2) Rating IMDb por decisión
    elif view == "Rating IMDb por decisión":
        if "imdb_rating" not in df_g.columns or "decision" not in df_g.columns:
            st.info("Faltan columnas imdb_rating o decision.")
        else:
            chart = (
                alt.Chart(df_g.dropna(subset=["imdb_rating"]))
                .mark_boxplot()
                .encode(
                    x=alt.X("decision:N", title="Decisión"),
                    y=alt.Y("imdb_rating:Q", title="IMDb rating"),
                    color=decision_color("decision"),
                    tooltip=["decision"],
                )
            )
            st.altair_chart(chart, use_container_width=True)

    # 3) Ratings IMDb vs RT
    elif view == "Ratings IMDb vs RT":
        if "imdb_rating" not in df_g.columns or "rt_score" not in df_g.columns:
            st.info("Faltan columnas imdb_rating o rt_score.")
        else:
            chart = (
                alt.Chart(df_g.dropna(subset=["imdb_rating", "rt_score"]))
                .mark_circle(size=60, opacity=0.7)
                .encode(
                    x=alt.X("imdb_rating:Q", title="IMDb rating"),
                    y=alt.Y("rt_score:Q", title="RT score (%)"),
                    color=decision_color("decision"),
                    tooltip=[
                        "title",
                        "year",
                        "library",
                        "imdb_rating",
                        "rt_score",
                        "imdb_votes",
                        "decision",
                    ],
                )
            )
            st.altair_chart(chart, use_container_width=True)

    # 4) Distribución por década
    elif view == "Distribución por década":
        if "decade_label" not in df_g.columns:
            st.info("Falta columna decade_label.")
        else:
            agg = (
                df_g.dropna(subset=["decade_label"])
                .groupby(["decade_label", "decision"])
                ["title"]
                .count()
                .reset_index()
            )
            agg = agg.rename(columns={"title": "count"})

            chart = (
                alt.Chart(agg)
                .mark_bar()
                .encode(
                    x=alt.X("decade_label:N", title="Década"),
                    y=alt.Y("count:Q", title="Número de películas"),
                    color=decision_color("decision"),
                    tooltip=["decade_label", "decision", "count"],
                )
            )
            st.altair_chart(chart, use_container_width=True)

    # 5) Distribución por biblioteca
    elif view == "Distribución por biblioteca":
        if "library" not in df_g.columns:
            st.info("Falta columna library.")
        else:
            agg = (
                df_g.groupby(["library", "decision"])["title"]
                .count()
                .reset_index()
                .rename(columns={"title": "count"})
            )

            chart = (
                alt.Chart(agg)
                .mark_bar()
                .encode(
                    x=alt.X("library:N", title="Biblioteca"),
                    y=alt.Y("count:Q", title="Número de películas", stack="normalize"),
                    color=decision_color("decision"),
                    tooltip=["library", "decision", "count"],
                )
            )
            st.altair_chart(chart, use_container_width=True)

    # 6) Distribución por género (OMDb)
    elif view == "Distribución por género (OMDb)":
        df_gen = explode_genres_from_omdb_json(df_g)

        if df_gen.empty:
            st.info("No hay datos de género en omdb_json.")
        else:
            agg = (
                df_gen.groupby(["genre", "decision"])["title"]
                .count()
                .reset_index()
                .rename(columns={"title": "count"})
            )

            top_n = st.slider("Top N géneros", 5, 50, 20)
            top_genres = (
                agg.groupby("genre")["count"].sum().sort_values(ascending=False).head(top_n).index
            )
            agg = agg[agg["genre"].isin(top_genres)]

            chart = (
                alt.Chart(agg)
                .mark_bar()
                .encode(
                    x=alt.X("genre:N", title="Género"),
                    y=alt.Y("count:Q", title="Número de películas", stack="normalize"),
                    color=decision_color("decision"),
                    tooltip=["genre", "decision", "count"],
                )
            )

            st.altair_chart(chart, use_container_width=True)

    # 7) Espacio ocupado por biblioteca/decisión
    elif view == "Espacio ocupado por biblioteca/decisión":
        if "file_size_gb" not in df_g.columns or "library" not in df_g.columns:
            st.info("Faltan columnas file_size_gb o library.")
        else:
            agg = (
                df_g.groupby(["library", "decision"])["file_size_gb"]
                .sum()
                .reset_index()
            )

            if agg.empty:
                st.info("No hay datos de tamaño de archivos.")
            else:
                chart_space = (
                    alt.Chart(agg)
                    .mark_bar()
                    .encode(
                        x=alt.X("library:N", title="Biblioteca"),
                        y=alt.Y("file_size_gb:Q", title="Tamaño (GB)", stack="normalize"),
                        color=decision_color("decision"),
                        tooltip=[
                            "library",
                            "decision",
                            alt.Tooltip("file_size_gb:Q", format=".2f"),
                        ],
                    )
                )
                st.altair_chart(chart_space, use_container_width=True)

                total_space = agg["file_size_gb"].sum()
                space_delete = agg[agg["decision"] == "DELETE"]["file_size_gb"].sum()
                space_maybe = agg[agg["decision"] == "MAYBE"]["file_size_gb"].sum()

                st.markdown(
                    f"- Espacio total: **{total_space:.2f} GB**\n"
                    f"- DELETE: **{space_delete:.2f} GB**\n"
                    f"- MAYBE: **{space_maybe:.2f} GB**"
                )

    # 8) Boxplot IMDb por biblioteca
    elif view == "Boxplot IMDb por biblioteca":
        if "imdb_rating" in df_g.columns and "library" in df_g.columns:
            chart_box = (
                alt.Chart(df_g.dropna(subset=["imdb_rating", "library"]))
                .mark_boxplot()
                .encode(
                    x=alt.X("library:N", title="Biblioteca"),
                    y=alt.Y("imdb_rating:Q", title="IMDb rating"),
                    tooltip=["library"],
                )
            )
            st.altair_chart(chart_box, use_container_width=True)
        else:
            st.info("Faltan columnas imdb_rating / library.")

    # 9) Ranking de directores
    elif view == "Ranking de directores":
        if "omdb_json" not in df_all.columns:
            st.info("No existe información OMDb JSON (omdb_json).")
        else:
            df_dir = df_all.copy()

            def extract_directors(raw):
                d = safe_json_loads_single(raw)
                if not isinstance(d, dict):
                    return []
                val = d.get("Director")
                if not val:
                    return []
                return [x.strip() for x in str(val).split(",") if x.strip()]

            df_dir["director_list"] = df_dir["omdb_json"].apply(extract_directors)
            df_dir = df_dir.explode("director_list")
            df_dir = df_dir[df_dir["director_list"].notna() & (df_dir["director_list"] != "")]

            if df_dir.empty:
                st.info("No se encontraron directores en omdb_json.")
            else:
                min_movies = st.slider("Mínimo nº de películas por director", 1, 10, 3)

                agg = (
                    df_dir.groupby("director_list")
                    .agg(
                        imdb_mean=("imdb_rating", "mean"),
                        count=("title", "count"),
                    )
                    .reset_index()
                )
                agg = agg[agg["count"] >= min_movies].sort_values("imdb_mean", ascending=False)

                top_n = st.slider("Top N directores por IMDb medio", 5, 50, 20)
                agg_top = agg.head(top_n)

                chart = (
                    alt.Chart(agg_top)
                    .mark_bar()
                    .encode(
                        x=alt.X("director_list:N", title="Director"),
                        y=alt.Y("imdb_mean:Q", title="IMDb medio"),
                        tooltip=["director_list", "imdb_mean", "count"],
                    )
                )
                st.altair_chart(chart, use_container_width=True)

    # 10) Palabras más frecuentes en títulos DELETE/MAYBE
    elif view == "Palabras más frecuentes en títulos DELETE/MAYBE":
        df_words = build_word_counts(df_g, ["DELETE", "MAYBE"])

        if df_words.empty:
            st.info("No hay datos suficientes para el análisis de palabras.")
        else:
            top_n = st.slider("Top N palabras", 5, 50, 20)
            df_top = df_words.head(top_n)

            chart = (
                alt.Chart(df_top)
                .mark_bar()
                .encode(
                    x=alt.X("word:N", title="Palabra"),
                    y=alt.Y("count:Q", title="Frecuencia"),
                    color=decision_color("decision"),
                    tooltip=["word", "decision", "count"],
                )
            )
            st.altair_chart(chart, use_container_width=True)

# ----------------------------------------------------
# Tab 6: Metadata
# ----------------------------------------------------
with tab6:
    st.write("### Corrección de metadata (sugerencias)")

    if not os.path.exists(METADATA_SUGG_CSV):
        st.info("No se encontró el CSV de sugerencias de metadata.")
    else:
        df_meta = pd.read_csv(METADATA_SUGG_CSV)

        st.write(
            "Este CSV contiene sugerencias de posibles errores de metadata en Plex.\n"
            "Puedes filtrarlo y exportarlo si lo necesitas."
        )

        col_f1, col_f2 = st.columns(2)

        with col_f1:
            lib_filter = st.multiselect(
                "Biblioteca", sorted(df_meta["library"].dropna().unique().tolist())
            )
        with col_f2:
            action_filter = st.multiselect(
                "Acción sugerida", sorted(df_meta["action"].dropna().unique().tolist())
            )

        if lib_filter:
            df_meta = df_meta[df_meta["library"].isin(lib_filter)]
        if action_filter:
            df_meta = df_meta[df_meta["action"].isin(action_filter)]

        st.write(f"Filas: {len(df_meta)}")

        st.dataframe(df_meta, use_container_width=True, height=400)

        csv_export = df_meta.to_csv(index=False).encode("utf-8")
        st.download_button(
            "💾 Descargar CSV filtrado",
            data=csv_export,
            file_name="metadata_suggestions_filtered.csv",
            mime="text/csv",
        )