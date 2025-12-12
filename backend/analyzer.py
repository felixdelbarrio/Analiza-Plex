# backend/analyzer.py
import json
from typing import Any, Dict, List, Optional, Tuple

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


def analyze_single_movie(
    movie,
) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]], List[str]]:

    logs: List[str] = []

    library = getattr(movie, "librarySectionTitle", None)
    title = getattr(movie, "title", None)
    year = getattr(movie, "year", None)
    plex_rating = getattr(movie, "rating", None)
    rating_key = getattr(movie, "ratingKey", None)
    guid = getattr(movie, "guid", None)
    thumb = getattr(movie, "thumb", None)

    # 1. Info de archivo
    file_path, file_size = get_movie_file_info(movie)

    # 2. Intento inicial de IMDb ID desde Plex
    imdb_id_hint = get_imdb_id_from_movie(movie)
    search_title = get_best_search_title(movie)

    # 3. MASTER RECORD = wiki_cache + wikidata + OMDb
    omdb_like_data = get_movie_record(
        title=search_title,
        year=year,
        imdb_id_hint=imdb_id_hint,
    )

    # Si no existe ningún dato útil
    if not omdb_like_data:
        imdb_rating = None
        imdb_votes = None
        rt_score = None
        imdb_id = imdb_id_hint
        decision = "UNKNOWN"
        reason = "Sin datos"
        misidentified_hint = ""
        meta_sugg = None
        poster_url = None
        trailer_url = None
        omdb_json_str = None
        wiki_meta = {}
    else:
        imdb_id = omdb_like_data.get("imdbID") or imdb_id_hint
        wiki_meta = omdb_like_data.get("__wiki") or {}

        imdb_rating, imdb_votes, rt_score = extract_ratings_from_omdb(omdb_like_data)
        decision, reason = decide_action(imdb_rating, imdb_votes, rt_score, year)

        misidentified_hint = detect_misidentified(
            title, year, omdb_like_data, imdb_rating, imdb_votes, rt_score
        )
        if misidentified_hint:
            logs.append(
                f"[MISIDENTIFIED] {library} / {title} ({year}): {misidentified_hint}"
            )

        meta_sugg = generate_metadata_suggestions_row(movie, omdb_like_data)
        if meta_sugg:
            logs.append(
                f"[METADATA_SUGG] {library} / {title} ({year}): "
                f"{meta_sugg.get('suggestions_json')}"
            )

        poster_url = omdb_like_data.get("Poster")
        trailer_url = omdb_like_data.get("Website")
        omdb_json_str = json.dumps(omdb_like_data, ensure_ascii=False)

        if wiki_meta:
            logs.append(
                f"[WIKI] Enriquecido desde Wikipedia/Wikidata: "
                f"wikidata_id={wiki_meta.get('wikidata_id')}, "
                f"wikipedia_title='{wiki_meta.get('wikipedia_title')}', "
                f"lang={wiki_meta.get('source_lang')}"
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