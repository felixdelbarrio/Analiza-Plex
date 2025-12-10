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

    partial = selected_raw[0]
    final_row = {col: partial.get(col, None) for col in df.columns}

    return final_row


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
        if isinstance(omdb_dict, dict):
            val = omdb_dict.get(key)
            if val is not None and str(val).strip() not in ("", "nan", "None"):
                return val
        return None

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

    # Campos OMDb extra: preferimos lo del JSON si está
    rated = from_omdb("Rated") or safe("Rated", "rated")
    released = from_omdb("Released") or safe("Released", "released")
    runtime = from_omdb("Runtime") or safe("Runtime", "runtime")
    genre = from_omdb("Genre") or safe("Genre", "genre")
    director = from_omdb("Director") or safe("Director", "director")
    writer = from_omdb("Writer") or safe("Writer", "writer")
    actors = from_omdb("Actors") or safe("Actors", "actors")
    language = from_omdb("Language") or safe("Language", "language")
    country = from_omdb("Country") or safe("Country", "country")
    awards = from_omdb("Awards") or safe("Awards", "awards")

    plot = (
        from_omdb("Plot")
        or safe("plot", "Plot")
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
        full_row = dict(row)
        if omdb_dict is not None:
            full_row["_omdb_parsed"] = omdb_dict
        st.json(full_row)


def render_modal():
    """
    Ventana modal superpuesta — usa sesión como estado.
    Sin overlay oscurecedor para mantener brillo/color homogéneo.
    """
    if not st.session_state["modal_open"]:
        return

    row = st.session_state["modal_row"]
    if row is None:
        return

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

# Campos texto importantes
for col in ["poster_url", "trailer_url", "omdb_json"]:
    if col in df_all.columns:
        df_all[col] = df_all[col].astype(str)

# Columnas derivadas ligeras (no parseamos omdb_json aquí)
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
# Tab 5: Gráficos AVANZADOS con selector
# ----------------------------------------------------
with tab5:
    st.write("### 📊 Gráficos")

    if df_all.empty:
        st.warning("No hay datos para mostrar.")
    else:
        view = st.selectbox(
            "Selecciona vista de análisis",
            [
                "Resumen calidad por biblioteca",
                "Distribución por géneros",
                "Distribución por décadas",
                "IMDb vs nº votos",
                "IMDb vs tamaño de archivo",
                "Espacio ocupado por biblioteca",
                "Boxplot IMDb por biblioteca",
                "Ranking de directores",
                "Palabras frecuentes en títulos (KEEP vs DELETE)",
                "Simulador de limpieza por umbrales",
            ],
        )

        # Filtro opcional por biblioteca
        libs = ["(Todas)"] + sorted(df_all["library"].dropna().unique())
        sel_lib = st.selectbox("Filtrar por biblioteca (opcional)", libs)
        df_g = df_all.copy()
        if sel_lib != "(Todas)":
            df_g = df_g[df_g["library"] == sel_lib]

        # 1) Resumen calidad por biblioteca
        if view == "Resumen calidad por biblioteca":
            if "library" in df_g.columns and "imdb_rating" in df_g.columns:
                agg = (
                    df_g.groupby("library")
                    .agg(
                        imdb_mean=("imdb_rating", "mean"),
                        count=("title", "count"),
                    )
                    .reset_index()
                )

                base = alt.Chart(agg)

                c1 = base.mark_bar().encode(
                    x=alt.X("library:N", title="Biblioteca"),
                    y=alt.Y("imdb_mean:Q", title="IMDb medio"),
                    tooltip=["library", alt.Tooltip("imdb_mean:Q", format=".2f")],
                )

                c2 = base.mark_line(point=True).encode(
                    x="library:N",
                    y=alt.Y("count:Q", title="Nº de películas"),
                    tooltip=["library", "count"],
                )

                st.altair_chart((c1 + c2).resolve_scale(y="independent"), use_container_width=True)
            else:
                st.info("Faltan columnas 'library' o 'imdb_rating'.")

        # 2) Géneros
        elif view == "Distribución por géneros":
            df_genres = explode_genres_from_omdb_json(df_g)
            if df_genres.empty:
                st.info("No se encontraron géneros (omdb_json / Genre).")
            else:
                decs = sorted(df_genres["decision"].dropna().unique())
                dec_sel = st.multiselect("Filtrar decisiones", decs, default=decs)
                if dec_sel:
                    df_genres = df_genres[df_genres["decision"].isin(dec_sel)]

                counts_gen = (
                    df_genres.groupby(["genre", "decision"])["title"]
                    .count()
                    .reset_index()
                    .rename(columns={"title": "count"})
                )

                chart_gen = (
                    alt.Chart(counts_gen)
                    .mark_bar()
                    .encode(
                        x=alt.X("count:Q", title="Nº películas"),
                        y=alt.Y("genre:N", sort="-x", title="Género"),
                        color=decision_color("decision"),
                        tooltip=["genre", "decision", "count"],
                    )
                )
                st.altair_chart(chart_gen, use_container_width=True)

        # 3) Décadas
        elif view == "Distribución por décadas":
            if "decade_label" not in df_g.columns:
                st.info("No hay información suficiente de 'year' para calcular décadas.")
            else:
                df_dec = df_g.dropna(subset=["decade_label"]).copy()
                counts_year_dec = (
                    df_dec.groupby(["decade_label", "decision"])["title"]
                    .count()
                    .reset_index()
                    .rename(columns={"title": "count"})
                )
                chart_year = (
                    alt.Chart(counts_year_dec)
                    .mark_bar()
                    .encode(
                        x=alt.X("decade_label:O", title="Década"),
                        y=alt.Y("count:Q", stack="normalize", title="% de películas"),
                        color=decision_color("decision"),
                        tooltip=["decade_label", "decision", "count"],
                    )
                )
                st.altair_chart(chart_year, use_container_width=True)

        # 4) IMDb vs votos
        elif view == "IMDb vs nº votos":
            if "imdb_rating" in df_g.columns and "imdb_votes" in df_g.columns:
                chart_scatter = (
                    alt.Chart(df_g.dropna(subset=["imdb_rating", "imdb_votes"]))
                    .mark_circle(size=60, opacity=0.7)
                    .encode(
                        x=alt.X("imdb_rating:Q", title="IMDb rating"),
                        y=alt.Y("imdb_votes:Q", title="IMDb votos", scale=alt.Scale(type="log", nice=True)),
                        color=decision_color("decision"),
                        tooltip=["title", "year", "imdb_rating", "imdb_votes", "decision"],
                    )
                    .interactive()
                )
                st.altair_chart(chart_scatter, use_container_width=True)
            else:
                st.info("Faltan columnas imdb_rating / imdb_votes.")

        # 5) IMDb vs tamaño
        elif view == "IMDb vs tamaño de archivo":
            if "imdb_rating" in df_g.columns and "file_size_gb" in df_g.columns:
                chart_scatter = (
                    alt.Chart(df_g.dropna(subset=["imdb_rating", "file_size_gb"]))
                    .mark_circle(size=60, opacity=0.7)
                    .encode(
                        x=alt.X("imdb_rating:Q", title="IMDb rating"),
                        y=alt.Y("file_size_gb:Q", title="Tamaño (GB)"),
                        color=decision_color("decision"),
                        tooltip=["title", "year", "imdb_rating", "file_size_gb", "decision"],
                    )
                    .interactive()
                )
                st.altair_chart(chart_scatter, use_container_width=True)
            else:
                st.info("Faltan columnas imdb_rating / file_size_gb.")

        # 6) Espacio por biblioteca
        elif view == "Espacio ocupado por biblioteca":
            if "file_size_gb" not in df_all.columns:
                st.info("No existe información de tamaño (file_size).")
            else:
                agg = (
                    df_all.groupby(["library", "decision"])["file_size_gb"]
                    .sum()
                    .reset_index()
                )
                agg["file_size_gb"] = agg["file_size_gb"].fillna(0.0)

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

        # 7) Boxplot IMDb por biblioteca
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

        # 8) Ranking directores
        elif view == "Ranking de directores":
            # Director solo se obtiene del JSON; lo parseamos aquí
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

                    chart_dir = (
                        alt.Chart(agg_top)
                        .mark_bar()
                        .encode(
                            x=alt.X("imdb_mean:Q", title="IMDb medio"),
                            y=alt.Y("director_list:N", sort="-x", title="Director"),
                            tooltip=[
                                "director_list",
                                alt.Tooltip("imdb_mean:Q", format=".2f"),
                                "count",
                            ],
                        )
                    )
                    st.altair_chart(chart_dir, use_container_width=True)

        # 9) Palabras frecuentes en títulos
        elif view == "Palabras frecuentes en títulos (KEEP vs DELETE)":
            if "title" not in df_all.columns or "decision" not in df_all.columns:
                st.info("Faltan columnas title / decision.")
            else:
                df_words = build_word_counts(df_all, ["KEEP", "DELETE"])
                if df_words.empty:
                    st.info("No se pudieron generar recuentos de palabras.")
                else:
                    top_n = st.slider("Top N palabras por decisión", 5, 50, 20)
                    df_words_top = (
                        df_words.groupby("decision")
                        .apply(lambda g: g.nlargest(top_n, "count"))
                        .reset_index(drop=True)
                    )

                    chart_words = (
                        alt.Chart(df_words_top)
                        .mark_bar()
                        .encode(
                            x=alt.X("count:Q", title="Frecuencia"),
                            y=alt.Y("word:N", sort="-x", title="Palabra"),
                            color=decision_color("decision"),
                            tooltip=["word", "decision", "count"],
                        )
                    )
                    st.altair_chart(chart_words, use_container_width=True)

        # 10) Simulador de limpieza
        elif view == "Simulador de limpieza por umbrales":
            col_s1, col_s2, col_s3 = st.columns(3)
            with col_s1:
                imdb_thr = st.slider("IMDb máximo para borrar", 0.0, 10.0, 6.0, 0.1)
            with col_s2:
                rt_thr = st.slider("RT máximo para borrar", 0, 100, 50, 5)
            with col_s3:
                votes_thr = st.slider("Votes máximo para borrar", 0, 100_000, 5_000, 500)

            df_sim = df_all.copy()
            cond_imdb = df_sim["imdb_rating"].fillna(0) <= imdb_thr
            cond_rt = df_sim["rt_score"].fillna(0) <= rt_thr
            cond_votes = df_sim["imdb_votes"].fillna(0) <= votes_thr
            cond_delete = cond_imdb | cond_rt | cond_votes

            df_to_delete = df_sim[cond_delete].copy()
            n_delete = len(df_to_delete)

            if "file_size_gb" in df_sim.columns:
                gb_delete = df_to_delete["file_size_gb"].sum(skipna=True)
            else:
                gb_delete = None

            st.markdown(
                f"- Películas que se borrarían con estos umbrales: **{n_delete}**\n"
                + (
                    f"- Espacio potencial a liberar: **{gb_delete:.2f} GB**"
                    if gb_delete is not None
                    else "- No hay información de tamaño de archivo."
                )
            )

            if not df_to_delete.empty:
                agg_sim = (
                    df_to_delete.groupby("library")["title"]
                    .count()
                    .reset_index()
                    .rename(columns={"title": "count"})
                )

                chart_sim = (
                    alt.Chart(agg_sim)
                    .mark_bar()
                    .encode(
                        x=alt.X("library:N", title="Biblioteca"),
                        y=alt.Y("count:Q", title="Películas que caerían"),
                        tooltip=["library", "count"],
                    )
                )
                st.altair_chart(chart_sim, use_container_width=True)

                st.markdown("#### Muestra de títulos afectados")
                st.dataframe(
                    df_to_delete[
                        [
                            "library",
                            "title",
                            "year",
                            "imdb_rating",
                            "rt_score",
                            "imdb_votes",
                            "file_size_gb",
                        ]
                    ].head(50),
                    use_container_width=True,
                )

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