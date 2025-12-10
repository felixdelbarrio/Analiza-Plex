import os
from pathlib import Path
from typing import Tuple, List

import pandas as pd


def delete_files_from_rows(
    rows: pd.DataFrame,
    delete_dry_run: bool,
) -> Tuple[int, int, List[str]]:
    """
    Borra físicamente archivos según las rutas de la columna 'file'.

    Parámetros:
      - rows: DataFrame con al menos columnas 'file' y 'title'.
      - delete_dry_run:
          * True  -> solo log, NO borra nada.
          * False -> borra de verdad.

    Devuelve:
      - num_ok: número de borrados correctos.
      - num_error: número de errores al borrar.
      - logs: lista de mensajes de log.
    """
    num_ok = 0
    num_error = 0
    logs: List[str] = []

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

        if delete_dry_run:
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