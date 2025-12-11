# backend/summary.py
from typing import Any, Dict, Optional

import pandas as pd

from backend.stats import (
    compute_global_imdb_mean_from_df,
    get_global_imdb_mean_from_cache,
)


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
      - delete_count
      - delete_size_gb
      - maybe_count
      - maybe_size_gb
      - imdb_mean_df          (media IMDb calculada sobre df_all)
      - imdb_mean_cache       (media IMDb global desde omdb_cache / BAYES_DEFAULT)
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

    # DELETE / MAYBE combinados
    dm_mask = df_all["decision"].isin(["DELETE", "MAYBE"])
    dm_count = int(dm_mask.sum())
    if "file_size_gb" in df_all.columns:
        dm_size = df_all.loc[dm_mask, "file_size_gb"].sum(skipna=True)
    else:
        dm_size = None

    # DELETE solo
    del_mask = df_all["decision"] == "DELETE"
    delete_count = int(del_mask.sum())
    if "file_size_gb" in df_all.columns:
        delete_size = df_all.loc[del_mask, "file_size_gb"].sum(skipna=True)
    else:
        delete_size = None

    # MAYBE solo
    maybe_mask = df_all["decision"] == "MAYBE"
    maybe_count = int(maybe_mask.sum())
    if "file_size_gb" in df_all.columns:
        maybe_size = df_all.loc[maybe_mask, "file_size_gb"].sum(skipna=True)
    else:
        maybe_size = None

    # Medias IMDb
    imdb_mean_df: Optional[float] = compute_global_imdb_mean_from_df(df_all)
    imdb_mean_cache: float = get_global_imdb_mean_from_cache()

    return {
        "total_count": total_count,
        "total_size_gb": total_size,
        "keep_count": keep_count,
        "keep_size_gb": keep_size,
        "dm_count": dm_count,
        "dm_size_gb": dm_size,
        "delete_count": delete_count,
        "delete_size_gb": delete_size,
        "maybe_count": maybe_count,
        "maybe_size_gb": maybe_size,
        "imdb_mean_df": imdb_mean_df,
        "imdb_mean_cache": imdb_mean_cache,
    }