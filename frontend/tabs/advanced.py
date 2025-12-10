import pandas as pd
import streamlit as st

from frontend.components import aggrid_with_row_click, render_detail_card


def render(df_all: pd.DataFrame) -> None:
    """Pestaña 3: Búsqueda avanzada."""
    st.write("### Búsqueda avanzada")

    df_view = df_all.copy()

    col_f1, col_f2, col_f3, col_f4 = st.columns(4)

    with col_f1:
        lib_filter = st.multiselect(
            "Biblioteca",
            sorted(df_view["library"].dropna().unique().tolist()),
            key="lib_filter_advanced",
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
        render_detail_card(selected_row, button_key_prefix="advanced")