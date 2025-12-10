import json
from typing import Optional, Dict, Any, List

from backend.config import METADATA_DRY_RUN, METADATA_APPLY_CHANGES


def _normalize_title(title: Optional[str]) -> Optional[str]:
    """Normaliza un título para comparaciones sencillas."""
    if title is None:
        return None
    t = str(title).strip()
    if not t:
        return None
    return t


def _normalize_year(year: Optional[Any]) -> Optional[int]:
    """Normaliza un año a int para comparaciones sencillas."""
    if year is None:
        return None
    try:
        y = int(str(year))
    except (TypeError, ValueError):
        return None
    return y


def generate_metadata_suggestions_row(
    movie: Any,
    omdb_data: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
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

    omdb_title = omdb_data.get("Title")
    omdb_year = omdb_data.get("Year")

    n_plex_title = _normalize_title(plex_title)
    n_omdb_title = _normalize_title(omdb_title)

    n_plex_year = _normalize_year(plex_year)
    n_omdb_year = _normalize_year(omdb_year)

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

    suggestions: Dict[str, Any] = {}
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

    row = {
        "plex_guid": plex_guid,
        "library": library,
        "plex_title": plex_title,
        "plex_year": plex_year,
        "omdb_title": omdb_title,
        "omdb_year": omdb_year,
        "action": action,
        "suggestions_json": json.dumps(suggestions, ensure_ascii=False),
    }

    return row


def apply_metadata_suggestion(
    movie: Any,
    suggestion_row: Dict[str, Any],
) -> List[str]:
    """
    Aplica una sugerencia de metadata a un objeto de Plex.

    Ahora mismo mantiene el comportamiento seguro:
      - Si METADATA_APPLY_CHANGES es False, SOLO loggea lo que haría.
      - Si es True y METADATA_DRY_RUN es False, intentará aplicar cambios
        usando atributos simples de movie (title / year).

    Devuelve una lista de líneas de log con las acciones realizadas.
    """
    logs: List[str] = []

    plex_title = getattr(movie, "title", None)
    plex_year = getattr(movie, "year", None)
    library = getattr(movie, "librarySectionTitle", None)
    plex_guid = getattr(movie, "guid", None)

    suggestions_json = suggestion_row.get("suggestions_json")
    try:
        suggestions = json.loads(suggestions_json) if suggestions_json else {}
    except Exception:
        suggestions = {}

    new_title = suggestions.get("new_title")
    new_year = suggestions.get("new_year")

    header = f"[APPLY_METADATA] {library} / {plex_title} ({plex_year}) guid={plex_guid}"
    logs.append(header)

    if not suggestions:
        logs.append("  - No hay sugerencias en suggestions_json.")
        return logs

    # Modo solo log (por defecto) si no se permiten cambios
    if not METADATA_APPLY_CHANGES:
        logs.append(
            f"  - METADATA_APPLY_CHANGES=False → solo log. "
            f"Sugerencias: title={new_title!r}, year={new_year!r}"
        )
        return logs

    if METADATA_DRY_RUN:
        logs.append(
            f"  - METADATA_DRY_RUN=True → NO se aplican cambios realmente. "
            f"Sugerencias: title={new_title!r}, year={new_year!r}"
        )
        return logs

    # Intento de aplicar cambios reales
    try:
        changed_fields = []

        if new_title is not None and new_title != plex_title:
            setattr(movie, "title", new_title)
            changed_fields.append("title")

        if new_year is not None and new_year != plex_year:
            try:
                setattr(movie, "year", int(new_year))
            except Exception:
                setattr(movie, "year", new_year)
            changed_fields.append("year")

        # Algunos clientes de Plex requieren save() o similar; si existe, lo llamamos.
        save_method = getattr(movie, "save", None)
        if callable(save_method) and changed_fields:
            save_method()

        if changed_fields:
            logs.append(f"  - Cambios aplicados en campos: {', '.join(changed_fields)}")
        else:
            logs.append("  - No se detectaron cambios a aplicar (ya coincide con OMDb).")

    except Exception as exc:  # pragma: no cover (por seguridad)
        logs.append(f"  - ERROR aplicando cambios de metadata: {exc!r}")

    return logs