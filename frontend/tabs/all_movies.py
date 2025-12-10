import pandas as pd
import streamlit as st

from frontend.components import aggrid_with_row_click, render_detail_card


def render(df_all: pd.DataFrame) -> None:
    """Pestaña 1: Todas las películas."""
    st.write("### Todas las películas")
    df_view = df_all.copy()
    col_grid, col_detail = st.columns([2, 1])
    with col_grid:
        selected_row = aggrid_with_row_click(df_view, "all")
    with col_detail:
        render_detail_card(selected_row)