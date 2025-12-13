import os
from typing import Any, Dict, Optional, Mapping

import pandas as pd
import streamlit as st
from st_aggrid import AgGrid, GridOptionsBuilder, GridUpdateMode

from frontend.data_utils import safe_json_loads_single


def aggrid_with_row_click(df: pd.DataFrame, key_suffix: str) -> Optional[Dict[str, Any]]:
    """
    Muestra un AgGrid con selección de una sola fila.
    Devuelve un dict con los valores de la fila seleccionada o None.
    """
    if df.empty:
        st.info("No hay datos para mostrar.")
        return None

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

    ordered_cols = visible_cols + [c for c in df.columns if c not in visible_cols]
    df = df[ordered_cols]

    gb = GridOptionsBuilder.from_dataframe(df)
    gb.configure_selection(selection_mode="single", use_checkbox=False)
    gb.configure_grid_options(domLayout="normal")

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

    # Normalizar distintos formatos que pueden venir desde AgGrid
    if selected_raw is None:
        return None

    # Si viene como DataFrame (raro, pero por compatibilidad), convertir
    if isinstance(selected_raw, pd.DataFrame):
        selected_rows = selected_raw.to_dict(orient="records")
    elif isinstance(selected_raw, list) or isinstance(selected_raw, tuple):
        selected_rows = list(selected_raw)
    elif isinstance(selected_raw, dict):
        # AgGrid normalmente devuelve lista, pero en caso aislado que venga dict
        selected_rows = [selected_raw]
    else:
        # Intentar convertir iterables seguros en lista, fall back a envolver el valor
        try:
            if hasattr(selected_raw, "__iter__") and not isinstance(selected_raw, (str, bytes)):
                selected_rows = list(selected_raw)
            else:
                selected_rows = [selected_raw]
        except Exception:
            selected_rows = [selected_raw]

    if len(selected_rows) == 0:
        return None

    # Asegurar que el primer elemento sea un dict
    first = selected_rows[0]
    if isinstance(first, pd.Series):
        return first.to_dict()
    if isinstance(first, dict):
        return first

    # Último recurso: intentar dict() o repr
    try:
        return dict(first)
    except Exception:
        return {"value": first}


def render_detail_card(
    row: Dict[str, Any],
    show_modal_button: bool = True,
    button_key_prefix: Optional[str] = None,
) -> None:
    """
    Panel lateral / ficha de detalle tipo Plex.
    Parseamos omdb_json SOLO para esta fila (si existe).

    button_key_prefix se usa para dar un key único al botón "Abrir en ventana"
    por pestaña (all / candidates / advanced, etc.) y evitar colisiones.
    """
    if row is None:
        st.info("Haz click en una fila para ver su detalle.")
        return

    # Aceptar pandas.Series o mappings diversos y normalizarlos a dict
    if isinstance(row, pd.Series):
        row = row.to_dict()
    elif not isinstance(row, Mapping):
        try:
            row = dict(row)
        except Exception:
            # No convertible: presentar mensaje y salir
            st.warning("Detalle no disponible: fila con formato inesperado.")
            return

    omdb_dict = None
    if "omdb_json" in row:
        try:
            omdb_dict = safe_json_loads_single(row.get("omdb_json"))
        except Exception:
            omdb_dict = None

    def from_omdb(key: str):
        if omdb_dict and isinstance(omdb_dict, dict):
            return omdb_dict.get(key)
        return None

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

    col_left, col_right = st.columns([1, 2])

    # POSTER + enlaces
    with col_left:
        if poster_url and str(poster_url).strip() and str(poster_url).lower() not in ("nan", "none"):
            st.image(poster_url, width=280)
        else:
            st.write("📷 Sin póster")

        if imdb_id:
            imdb_url = f"https://www.imdb.com/title/{imdb_id}"
            st.markdown(f"[🎬 Ver en IMDb]({imdb_url})")

        # Leer base de Plex desde varias posibles vars de entorno para mayor compatibilidad
        plex_base = os.getenv("PLEX_WEB_BASEURL") or os.getenv("PLEX_BASEURL") or ""
        if plex_base and rating_key:
            plex_url = f"{plex_base}/web/index.html#!/server/library/metadata/{rating_key}"
            st.markdown(f"[📺 Ver en Plex Web]({plex_url})")

        if show_modal_button:
            # Key único por pestaña para evitar StreamlitDuplicateElementKey
            key_suffix = button_key_prefix or "default"
            button_key = f"open_modal_{key_suffix}"
            if st.button("🪟 Abrir en ventana", key=button_key):
                # Guardar estado de modal de forma segura
                st.session_state["modal_row"] = row
                st.session_state["modal_open"] = True
                st.experimental_rerun()

    # DETALLE
    with col_right:
        header = title
        try:
            if pd.notna(year):
                header += f" ({int(float(year))})"
        except Exception:
            # ignorar año inválido
            pass

        st.markdown(f"### {header}")
        st.write(f"**Biblioteca:** {library}")
        st.write(f"**Decisión:** `{decision}` — {reason}")

        m1, m2, m3 = st.columns(3)
        # Conversores seguros
        def safe_number_to_str(v):
            try:
                if pd.isna(v):
                    return "N/A"
                return str(v)
            except Exception:
                return "N/A"

        def safe_votes(v):
            try:
                if pd.isna(v):
                    return "N/A"
                # eliminar comas y convertir a int
                if isinstance(v, str):
                    v2 = v.replace(",", "")
                    return int(float(v2))
                return int(float(v))
            except Exception:
                return "N/A"

        m1.metric("IMDb", safe_number_to_str(imdb_rating))
        m2.metric("RT", f"{safe_number_to_str(rt_score)}%" if safe_number_to_str(rt_score) != "N/A" else "N/A")
        m3.metric("Votos", safe_votes(imdb_votes))

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

        if plot and str(plot).strip():
            st.markdown("---")
            st.write("#### Sinopsis")
            st.write(str(plot))

        st.markdown("---")
        st.write("#### Archivo")
        if file_path:
            st.code(file_path, language="bash")
        if file_size is not None and pd.notna(file_size):
            try:
                gb = float(file_size) / (1024 ** 3)
                st.write(f"**Tamaño:** {gb:.2f} GB")
            except Exception:
                st.write(f"**Tamaño:** {file_size}")

        if trailer_url and str(trailer_url).strip() and str(trailer_url).lower() not in ("nan", "none"):
            st.markdown("#### 🎞 Tráiler")
            st.video(trailer_url)

    with st.expander("Ver JSON completo"):
        try:
            full_row = dict(row)
        except Exception:
            full_row = {"value": str(row)}
        if omdb_dict is not None:
            full_row["_omdb_parsed"] = omdb_dict
        st.json(full_row)


def render_modal() -> None:
    """
    Vista de detalle ampliado usando el estado global de Streamlit.
    """
    if not st.session_state.get("modal_open"):
        return

    row = st.session_state.get("modal_row")
    if row is None:
        return

    c1, c2 = st.columns([10, 1])
    with c1:
        st.markdown("### 🔍 Detalle ampliado")
    with c2:
        if st.button("✖", key="close_modal"):
            st.session_state["modal_open"] = False
            st.session_state["modal_row"] = None
            st.experimental_rerun()

    render_detail_card(row, show_modal_button=False)