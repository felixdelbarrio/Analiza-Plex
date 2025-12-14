from __future__ import annotations

import json
import re
from collections.abc import Mapping

from backend import logger as _logger
from backend.config import METADATA_DRY_RUN, METADATA_APPLY_CHANGES, SILENT_MODE


# -------------------------------------------------------------------
# Helpers de logging que respetan SILENT_MODE explícitamente
# -------------------------------------------------------------------


def _log_info(msg: str) -> None:
    if SILENT_MODE:
        return
    try:
        _logger.info(msg)
    except Exception:
        # Fallback muy defensivo
        print(msg)


def _log_debug(msg: str) -> None:
    if SILENT_MODE:
        return
    try:
        _logger.debug(msg)
    except Exception:
        # En debug, si falla el logger, simplemente no mostramos nada
        pass


def _log_warning(msg: str) -> None:
    if SILENT_MODE:
        return
    try:
        _logger.warning(msg)
    except Exception:
        print(msg)


def _log_error(msg: str) -> None:
    if SILENT_MODE:
        return
    try:
        _logger.error(msg)
    except Exception:
        print(msg)


# -------------------------------------------------------------------
# Normalización de campos
# -------------------------------------------------------------------


def _normalize_title(title: str | None) -> str | None:
    """Normaliza un título para comparaciones sencillas.

    - Convierte a minúsculas, elimina puntuación y colapsa espacios.
    - Devuelve None si el título es vacío o None.
    """
    if title is None:
        return None
    t = str(title).strip()
    if not t:
        return None
    t = t.lower()
    # eliminar caracteres no alfanuméricos dejando espacios
    t = re.sub(r"[^0-9a-záéíóúüñ\s]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t or None


def _normalize_year(year: object | None) -> int | None:
    """Normaliza un año a int para comparaciones sencillas."""
    if year is None:
        return None
    try:
        return int(str(year))
    except (TypeError, ValueError):
        return None


# -------------------------------------------------------------------
# Generación de sugerencias
# -------------------------------------------------------------------


def generate_metadata_suggestions_row(
    movie: object,
    omdb_data: Mapping[str, object] | None,
) -> dict[str, object] | None:
    """
    Genera una fila de sugerencias de metadata si detecta diferencias
    entre los datos de Plex y los datos de OMDb.

    Devuelve:
      - dict con las columnas para el CSV de sugerencias, incluyendo:
        - plex_guid
        - library
        - plex_title
        - plex_year
        - omdb_title
        - omdb_year
        - action            (Fix title / Fix year / Fix title & year)
        - suggestions_json  (JSON con new_title / new_year)
      - None si no se detecta ninguna diferencia relevante.
    """
    if not omdb_data:
        return None

    plex_title = getattr(movie, "title", None)
    plex_year = getattr(movie, "year", None)
    library = getattr(movie, "librarySectionTitle", None)
    plex_guid = getattr(movie, "guid", None)

    omdb_title_obj = omdb_data.get("Title")
    omdb_year_obj = omdb_data.get("Year")

    omdb_title = omdb_title_obj if isinstance(omdb_title_obj, str) else None

    n_plex_title = _normalize_title(plex_title if isinstance(plex_title, str) else None)
    n_omdb_title = _normalize_title(omdb_title)

    n_plex_year = _normalize_year(plex_year)
    n_omdb_year = _normalize_year(omdb_year_obj)

    # Detectar diferencias
    title_diff = (
        n_plex_title is not None
        and n_omdb_title is not None
        and n_plex_title != n_omdb_title
    )
    year_diff = (
        n_plex_year is not None
        and n_omdb_year is not None
        and n_plex_year != n_omdb_year
    )

    if not title_diff and not year_diff:
        # No hay nada que sugerir
        return None

    suggestions: dict[str, object] = {}
    if title_diff:
        suggestions["new_title"] = omdb_title
    if year_diff:
        suggestions["new_year"] = n_omdb_year

    if title_diff and year_diff:
        action = "Fix title & year"
    elif title_diff:
        action = "Fix title"
    else:
        action = "Fix year"

    row: dict[str, object] = {
        "plex_guid": plex_guid,
        "library": library,
        "plex_title": plex_title,
        "plex_year": plex_year,
        "omdb_title": omdb_title_obj,
        "omdb_year": omdb_year_obj,
        "action": action,
        "suggestions_json": json.dumps(
            suggestions,
            ensure_ascii=False,
            separators=(",", ":"),
        ),
    }

    _log_debug(
        f"Generated metadata suggestion for {library} / {plex_title}: {suggestions}"
    )

    return row


# -------------------------------------------------------------------
# Aplicación de sugerencias
# -------------------------------------------------------------------


def apply_metadata_suggestion(
    movie: object,
    suggestion_row: dict[str, object],
) -> list[str]:
    """
    Aplica una sugerencia de metadata a un objeto de Plex.

    Ahora mismo mantiene el comportamiento seguro:
      - Si METADATA_APPLY_CHANGES es False, SOLO loggea lo que haría.
      - Si es True y METADATA_DRY_RUN es False, intentará aplicar cambios
        usando atributos simples de movie (title / year).

    Devuelve una lista de líneas de log con las acciones realizadas.
    """
    logs: list[str] = []

    plex_title = getattr(movie, "title", None)
    plex_year = getattr(movie, "year", None)
    library = getattr(movie, "librarySectionTitle", None)
    plex_guid = getattr(movie, "guid", None)

    suggestions_json_obj = suggestion_row.get("suggestions_json")
    suggestions: dict[str, object]

    if isinstance(suggestions_json_obj, dict):
        suggestions = suggestions_json_obj
    else:
        try:
            if isinstance(suggestions_json_obj, str) and suggestions_json_obj:
                parsed = json.loads(suggestions_json_obj)
                suggestions = parsed if isinstance(parsed, dict) else {}
            else:
                suggestions = {}
        except Exception:
            suggestions = {}

    new_title = suggestions.get("new_title")
    new_year = suggestions.get("new_year")

    header = (
        f"[APPLY_METADATA] {library} / {plex_title} ({plex_year}) "
        f"guid={plex_guid}"
    )
    logs.append(header)
    _log_info(header)

    if not suggestions:
        msg = "  - No hay sugerencias en suggestions_json."
        logs.append(msg)
        _log_debug(msg)
        return logs

    # Modo solo log (por defecto) si no se permiten cambios
    if not METADATA_APPLY_CHANGES:
        msg = (
            "  - METADATA_APPLY_CHANGES=False → solo log. "
            f"Sugerencias: title={new_title!r}, year={new_year!r}"
        )
        logs.append(msg)
        _log_info(msg)
        return logs

    if METADATA_DRY_RUN:
        msg = (
            "  - METADATA_DRY_RUN=True → NO se aplican cambios realmente. "
            f"Sugerencias: title={new_title!r}, year={new_year!r}"
        )
        logs.append(msg)
        _log_info(msg)
        return logs

    # Intento de aplicar cambios reales
    try:
        changed_fields: list[str] = []

        if new_title is not None and new_title != plex_title:
            try:
                setattr(movie, "title", new_title)
                changed_fields.append("title")
            except Exception as exc:
                _log_warning(f"No se pudo setear title en movie: {exc}")

        if new_year is not None and new_year != plex_year:
            try:
                int_year = int(new_year)  # type: ignore[arg-type]
                try:
                    setattr(movie, "year", int_year)
                except Exception:
                    setattr(movie, "year", new_year)
                changed_fields.append("year")
            except Exception:
                try:
                    setattr(movie, "year", new_year)
                    changed_fields.append("year")
                except Exception as exc:
                    _log_warning(f"No se pudo setear year en movie: {exc}")

        # Algunos clientes de Plex requieren save() o similar; si existe, lo llamamos.
        save_method = getattr(movie, "save", None)
        if callable(save_method) and changed_fields:
            try:
                save_method()
            except Exception as exc:
                _log_warning(f"save() falló al aplicar metadata: {exc}")

        if changed_fields:
            msg = (
                "  - Cambios aplicados en campos: "
                f"{', '.join(changed_fields)}"
            )
            logs.append(msg)
            _log_info(msg)
        else:
            msg = (
                "  - No se detectaron cambios a aplicar "
                "(ya coincide con OMDb)."
            )
            logs.append(msg)
            _log_debug(msg)

    except Exception as exc:  # pragma: no cover (por seguridad)
        msg = f"  - ERROR aplicando cambios de metadata: {exc!r}"
        logs.append(msg)
        _log_error(msg)

    return logs