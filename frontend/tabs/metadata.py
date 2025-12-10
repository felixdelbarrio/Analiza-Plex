import os

import pandas as pd
import streamlit as st


def render(metadata_sugg_csv: str) -> None:
    """Pestaña 6: Corrección de metadata (sugerencias)."""

    st.write("### Corrección de metadata (sugerencias)")

    if not os.path.exists(metadata_sugg_csv):
        st.info("No se encontró el CSV de sugerencias de metadata.")
        return

    df_meta = pd.read_csv(metadata_sugg_csv)

    st.write(
        "Este CSV contiene sugerencias de posibles errores de metadata en Plex.\n"
        "Puedes filtrarlo y exportarlo si lo necesitas."
    )

    col_f1, col_f2 = st.columns(2)

    with col_f1:
        lib_filter = st.multiselect(
            "Biblioteca",
            sorted(df_meta["library"].dropna().unique().tolist()),
            key="lib_filter_metadata",
        )
    with col_f2:
        if "action" in df_meta.columns:
            action_filter = st.multiselect(
                "Acción sugerida",
                sorted(df_meta["action"].dropna().unique().tolist()),
                key="action_filter_metadata",
            )
        else:
            action_filter = None

    if lib_filter:
        df_meta = df_meta[df_meta["library"].isin(lib_filter)]
    if action_filter and "action" in df_meta.columns:
        df_meta = df_meta[df_meta["action"].isin(action_filter)]

    st.write(f"Filas: {len(df_meta)}")

    st.dataframe(df_meta, width="stretch", height=400)

    csv_export = df_meta.to_csv(index=False).encode("utf-8")
    st.download_button(
        "💾 Descargar CSV filtrado",
        data=csv_export,
        file_name="metadata_suggestions_filtered.csv",
        mime="text/csv",
    )