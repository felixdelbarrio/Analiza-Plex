import os
from typing import Optional, Tuple

import pandas as pd

from frontend.data_utils import add_derived_columns


TEXT_COLUMNS = ["poster_url", "trailer_url", "omdb_json"]


def _clean_base_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """
    Elimina columnas no necesarias para el dashboard.
    Actualmente solo se elimina 'thumb' si existe.
    """
    cols = [c for c in df.columns if c != "thumb"]
    return df[cols]


def _cast_text_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    Asegura que ciertas columnas se traten como texto (str),
    evitando problemas al mostrarlas en el dashboard.
    """
    df = df.copy()
    for col in TEXT_COLUMNS:
        if col in df.columns:
            df[col] = df[col].astype(str)
    return df


def load_reports(
    all_csv_path: str,
    filtered_csv_path: str,
) -> Tuple[pd.DataFrame, Optional[pd.DataFrame]]:
    """
    Carga y prepara los DataFrames usados por el dashboard.

    - Lee el CSV completo (all_csv_path).
    - Si existe filtered_csv_path, lo carga también.
    - Hace:
        * cast de columnas de texto (poster_url, trailer_url, omdb_json)
        * columnas derivadas (add_derived_columns)
        * limpieza de columnas (elimina 'thumb')

    Devuelve:
      - df_all: DataFrame completo preparado.
      - df_filtered: DataFrame filtrado preparado o None si no existe el CSV.
    """
    if not os.path.exists(all_csv_path):
        raise FileNotFoundError(f"No se encontró el CSV completo: {all_csv_path}")

    # Carga del CSV completo
    df_all = pd.read_csv(all_csv_path)
    df_all = _cast_text_columns(df_all)
    df_all = add_derived_columns(df_all)
    df_all = _clean_base_dataframe(df_all)

    # Carga del CSV filtrado (opcional)
    if os.path.exists(filtered_csv_path):
        df_filtered = pd.read_csv(filtered_csv_path)
        df_filtered = _clean_base_dataframe(df_filtered)
    else:
        df_filtered = None

    return df_all, df_filtered