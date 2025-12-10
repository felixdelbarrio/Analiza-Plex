import pandas as pd
import streamlit as st

from frontend.components import aggrid_with_row_click, render_detail_card


def render(df_all: pd.DataFrame, df_filtered: pd.DataFrame | None) -> None:
    """Pestaña 2: Candidatas a borrar."""
    st.write("### Candidatas a borrar (DELETE / MAYBE)")
    if df_filtered is None or df_filtered.empty:
        st.info("No hay CSV filtrado o está vacío.")
        return

    df_view = df_filtered.copy()
    col_grid, col_detail = st.columns([2, 1])
    with col_grid:
        selected_row = aggrid_with_row_click(df_view, "filtered")
    with col_detail:
        render_detail_card(selected_row, button_key_prefix="candidates")