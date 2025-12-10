from typing import Dict, Any

import pandas as pd


def compute_summary(df_all: pd.DataFrame) -> Dict[str, Any]:
    """
    Calcula las métricas de resumen general a partir del DataFrame completo.

    Devuelve un diccionario con:
      - total_count
      - total_size_gb
      - keep_count
      - keep_size_gb
      - dm_count          (DELETE + MAYBE)
      - dm_size_gb
    """
    # Total de películas
    total_count = len(df_all)

    # Tamaño total en GB (si existe la columna file_size_gb)
    if "file_size_gb" in df_all.columns:
        total_size = df_all["file_size_gb"].sum(skipna=True)
    else:
        total_size = None

    # KEEP
    keep_mask = df_all["decision"] == "KEEP"
    keep_count = int(keep_mask.sum())
    if "file_size_gb" in df_all.columns:
        keep_size = df_all.loc[keep_mask, "file_size_gb"].sum(skipna=True)
    else:
        keep_size = None

    # DELETE / MAYBE
    dm_mask = df_all["decision"].isin(["DELETE", "MAYBE"])
    dm_count = int(dm_mask.sum())
    if "file_size_gb" in df_all.columns:
        dm_size = df_all.loc[dm_mask, "file_size_gb"].sum(skipna=True)
    else:
        dm_size = None

    return {
        "total_count": total_count,
        "total_size_gb": total_size,
        "keep_count": keep_count,
        "keep_size_gb": keep_size,
        "dm_count": dm_count,
        "dm_size_gb": dm_size,
    }