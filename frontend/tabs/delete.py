import pandas as pd
import streamlit as st
from st_aggrid import AgGrid, GridOptionsBuilder

from backend.delete_logic import delete_files_from_rows


def render(
    df_filtered: pd.DataFrame | None,
    delete_dry_run: bool,
    delete_require_confirm: bool,
) -> None:
    """Pestaña 4: Borrado controlado de archivos."""
    st.write("### Borrado controlado de archivos")

    if df_filtered is None or df_filtered.empty:
        st.info("No hay CSV filtrado. Ejecuta primero el análisis.")
        return

    st.warning(
        "⚠️ Cuidado: aquí puedes borrar archivos físicamente.\n\n"
        f"- DELETE_DRY_RUN = `{delete_dry_run}`\n"
        f"- DELETE_REQUIRE_CONFIRM = `{delete_require_confirm}`"
    )

    df_view = df_filtered.copy()

    st.write("Filtra las películas que quieras borrar y selecciónalas en la tabla:")

    col_f1, col_f2 = st.columns(2)

    with col_f1:
        lib_filter = st.multiselect(
            "Biblioteca",
            sorted(df_view["library"].dropna().unique().tolist()),
            key="lib_filter_delete",
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
        update_on="selection_changed",
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
        if delete_require_confirm:
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
                ok, err, logs = delete_files_from_rows(df_sel, delete_dry_run)

                st.success(f"Borrado completado. OK={ok}, errores={err}")
                st.text_area("Log de borrado", value="\n".join(logs), height=200)