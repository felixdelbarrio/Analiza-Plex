# backend/analyzer.py
import json
from typing import Any, Dict, List, Optional, Tuple

from backend.decision_logic import detect_misidentified
from backend.metadata_fix import generate_metadata_suggestions_row
from backend.omdb_client import extract_ratings_from_omdb
"""Funciones para analizar una única película de Plex y construir la fila final
que será consumida por `reporting` y el dashboard.

Objetivo: mantener la API pública (`analyze_single_movie(movie)`) y mejorar
robustez (manejo defensivo, tipos, logging, y parsing seguro de campos).
"""

import json
from typing import Any, Dict, List, Optional, Tuple

from backend import logger as _logger
from backend.decision_logic import detect_misidentified
from backend.metadata_fix import generate_metadata_suggestions_row
from backend.omdb_client import extract_ratings_from_omdb
from backend.plex_client import (
    get_best_search_title,
    get_imdb_id_from_movie,
    get_movie_file_info,
)
from backend.scoring import decide_action
from backend.wiki_client import get_movie_record


def _safe_int(value: Any) -> Optional[int]:
    try:
        if value is None:
            return None
        s = str(value).strip()
        if not s or s.upper() == "N/A":
            return None
        return int(s)
    except Exception:
        return None


def analyze_single_movie(movie: Any) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]], List[str]]:
    """Analiza un objeto `movie` devuelto por la API de Plex.

    Retorna una tupla: (row_dict, metadata_suggestion_row_or_None, logs).
    - `row_dict` es siempre un dict con claves usadas por `reporting` (si no
      hay datos, varias claves tendrán valor None).
    - `metadata_suggestion_row_or_None` es el resultado de `generate_metadata_suggestions_row`.
    - `logs` es una lista de cadenas con anotaciones útiles para debugging.
    """

    logs: List[str] = []

    library = getattr(movie, "librarySectionTitle", None)
    title = getattr(movie, "title", None)
    year = getattr(movie, "year", None)
    plex_rating = getattr(movie, "rating", None)
    rating_key = getattr(movie, "ratingKey", None)
    guid = getattr(movie, "guid", None)
    thumb = getattr(movie, "thumb", None)

    # 1) Info de archivo
    file_path, file_size = get_movie_file_info(movie)

    # 2) Intento inicial de IMDb ID desde Plex y mejor título de búsqueda
    imdb_id_hint = get_imdb_id_from_movie(movie)
    search_title = get_best_search_title(movie)

    # 3) MASTER RECORD (Wikipedia/Wikidata + OMDb)
    omdb_like_data = get_movie_record(title=search_title, year=year, imdb_id_hint=imdb_id_hint)

    # Inicializar valores por defecto
    imdb_rating = None
    imdb_votes = None
    rt_score = None
    metacritic_score: Optional[int] = None
    imdb_id = imdb_id_hint
    decision = "UNKNOWN"
    reason = "Sin datos"
    misidentified_hint = ""
    meta_sugg = None
    poster_url = None
    trailer_url = None
    omdb_json_str = None
    wiki_meta: Dict[str, Any] = {}

    if omdb_like_data:
        imdb_id = omdb_like_data.get("imdbID") or imdb_id_hint
        wiki_meta = omdb_like_data.get("__wiki") or {}

        # Ratings principales
        try:
            imdb_rating, imdb_votes, rt_score = extract_ratings_from_omdb(omdb_like_data)
        except Exception as e:
            _logger.warning(f"extract_ratings_from_omdb falló para {title!r}: {e}")

        # Metacritic (0-100) desde OMDb o wiki
        metacritic_score = _safe_int(omdb_like_data.get("Metascore"))
        if metacritic_score is None and wiki_meta:
            metacritic_score = _safe_int(wiki_meta.get("metacritic_score"))

        # Scoring final
        decision, reason = decide_action(
            imdb_rating, imdb_votes, rt_score, year, metacritic_score=metacritic_score
        )

        misidentified_hint = detect_misidentified(title, year, omdb_like_data, imdb_rating, imdb_votes, rt_score)
        if misidentified_hint:
            logs.append(f"[MISIDENTIFIED] {library} / {title} ({year}): {misidentified_hint}")

        try:
            meta_sugg = generate_metadata_suggestions_row(movie, omdb_like_data)
            if meta_sugg:
                logs.append(
                    f"[METADATA_SUGG] {library} / {title} ({year}): {meta_sugg.get('suggestions_json')}"
                )
        except Exception as e:
            _logger.warning(f"generate_metadata_suggestions_row falló para {title!r}: {e}")

        poster_url = omdb_like_data.get("Poster")
        trailer_url = omdb_like_data.get("Website")
        try:
            omdb_json_str = json.dumps(omdb_like_data, ensure_ascii=False)
        except Exception:
            omdb_json_str = str(omdb_like_data)

        if wiki_meta:
            logs.append(
                (
                    "[WIKI] Enriquecido desde Wikipedia/Wikidata: "
                    f"wikidata_id={wiki_meta.get('wikidata_id')}, "
                    f"wikipedia_title={wiki_meta.get('wikipedia_title')!r}, "
                    f"lang={wiki_meta.get('source_lang')}"
                )
            )

    # Construcción final de fila CSV
    row: Dict[str, Any] = {
        "library": library,
        "title": title,
        "year": year,
        "plex_rating": plex_rating,
        "imdb_rating": imdb_rating,
        "imdb_votes": imdb_votes,
        "rt_score": rt_score,
        "metacritic_score": metacritic_score,  # campo adicional para el dashboard
        "decision": decision,
        "reason": reason,
        "misidentified_hint": misidentified_hint,
        "file": file_path,
        "file_size": file_size,
        "rating_key": rating_key,
        "guid": guid,
        "imdb_id": imdb_id,
        "poster_url": poster_url,
        "trailer_url": trailer_url,
        "thumb": thumb,
        "omdb_json": omdb_json_str,
        "wikidata_id": wiki_meta.get("wikidata_id"),
        "wikipedia_title": wiki_meta.get("wikipedia_title"),
    }

    return row, meta_sugg, logs
