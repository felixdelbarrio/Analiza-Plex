import json
from typing import Optional, Dict, Any, List, Tuple

from backend.plex_client import (
    get_movie_file_info,
    get_imdb_id_from_plex_guid,
    get_best_search_title,
)
from backend.omdb_client import (
    extract_ratings_from_omdb,
    search_omdb_by_imdb_id,
    search_omdb_with_candidates,
)
from backend.decision_logic import (
    detect_misidentified,
)
from backend.scoring import decide_action
from backend.metadata_fix import (
    generate_metadata_suggestions_row,
)


def analyze_single_movie(
    movie,
) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]], List[str]]:
    """
    Analiza una película individual de Plex y devuelve:
      - row: dict con datos para *_all.csv
      - meta_sugg: dict con sugerencias de metadata (o None)
      - logs: mensajes para el metadata_log.txt
    """
    logs: List[str] = []

    library = getattr(movie, "librarySectionTitle", None)
    title = getattr(movie, "title", None)
    year = getattr(movie, "year", None)
    plex_rating = getattr(movie, "rating", None)
    rating_key = getattr(movie, "ratingKey", None)
    guid = getattr(movie, "guid", None)
    thumb = getattr(movie, "thumb", None)

    # Info de archivo
    file_path, file_size = get_movie_file_info(movie)

    # ID IMDb
    imdb_id = get_imdb_id_from_plex_guid(guid or "")

    # Búsqueda OMDb
    if imdb_id:
        omdb_data = search_omdb_by_imdb_id(imdb_id)
    else:
        search_title = get_best_search_title(movie)
        omdb_data = search_omdb_with_candidates(search_title, year)

    # Ratings y score
    imdb_rating, imdb_votes, rt_score = extract_ratings_from_omdb(omdb_data)

    # Decisión KEEP/MAYBE/DELETE/UNKNOWN
    decision, reason = decide_action(imdb_rating, imdb_votes, rt_score)

    # Posible misidentificación
    misidentified_hint = detect_misidentified(
        title, year, omdb_data, imdb_rating, imdb_votes, rt_score
    )
    if misidentified_hint:
        logs.append(
            f"[MISIDENTIFIED] {library} / {title} ({year}): {misidentified_hint}"
        )

    # Sugerencias metadata
    meta_sugg = generate_metadata_suggestions_row(movie, omdb_data)
    if meta_sugg:
        logs.append(
            f"[METADATA_SUGG] {library} / {title} ({year}): "
            f"{meta_sugg.get('suggestions_json')}"
        )

    # Extras OMDb (poster y trailer si existiera)
    poster_url = None
    trailer_url = None
    if omdb_data:
        poster_url = omdb_data.get("Poster")

    row = {
        "library": library,
        "title": title,
        "year": year,
        "plex_rating": plex_rating,
        "imdb_rating": imdb_rating,
        "imdb_votes": imdb_votes,
        "rt_score": rt_score,
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
        "omdb_json": json.dumps(omdb_data, ensure_ascii=False) if omdb_data else None,
    }

    return row, meta_sugg, logs