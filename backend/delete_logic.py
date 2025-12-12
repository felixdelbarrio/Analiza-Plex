import os
from pathlib import Path
from typing import Any, Iterable, List, Optional, Tuple, Union

from backend import logger as _logger


def delete_files_from_rows(
    rows: Union[Any, Iterable[dict]],
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

    # Support both a pandas.DataFrame (rows.iterrows()) or an iterable of dict-like
    iterator: Iterable = None  # type: ignore[assignment]
    try:
        import pandas as _pd  # local import to avoid hard dependency at module import

        if isinstance(rows, _pd.DataFrame):
            iterator = (row for _, row in rows.iterrows())
    except Exception:
        iterator = None

    if iterator is None:
        # Assume rows is an iterable of dict-like objects
        iterator = iter(rows)

    for row in iterator:
        # row may be a pandas Series (has .get) or a dict-like
        try:
            file_path = row.get("file") if hasattr(row, "get") else row["file"]
        except Exception:
            file_path = None
        try:
            title = row.get("title") if hasattr(row, "get") else row.get("title")
        except Exception:
            title = None

        if not file_path:
            msg = f"[SKIP] {title or '<no title>'} -> sin ruta de archivo"
            _logger.info(msg)
            logs.append(msg)
            continue

        try:
            p = Path(str(file_path)).resolve()
        except Exception as e:
            msg = f"[SKIP] {title or '<no title>'} -> ruta inválida: {file_path} ({e})"
            _logger.warning(msg)
            logs.append(msg)
            continue

        if not p.exists():
            msg = f"[SKIP] {title or '<no title>'} -> archivo no existe: {p}"
            _logger.info(msg)
            logs.append(msg)
            continue

        if not p.is_file():
            msg = f"[SKIP] {title or '<no title>'} -> no es un fichero: {p}"
            _logger.warning(msg)
            logs.append(msg)
            continue

        if delete_dry_run:
            msg = f"[DRY RUN] {title or '<no title>'} -> NO se borra: {p}"
            _logger.info(msg)
            logs.append(msg)
            continue

        try:
            p.unlink()
            msg = f"[OK] BORRADO {title or '<no title>'} -> {p}"
            _logger.info(msg)
            logs.append(msg)
            num_ok += 1
        except Exception as e:
            msg = f"[ERROR] {title or '<no title>'}: {e}"
            _logger.error(msg)
            logs.append(msg)
            num_error += 1

    return num_ok, num_error, logs