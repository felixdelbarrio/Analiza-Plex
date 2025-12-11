# backend/analyzer.py
import json
from typing import Any, Dict, List, Optional, Tuple

from backend.decision_logic import detect_misidentified
from backend.metadata_fix import generate_metadata_suggestions_row
from backend.omdb_client import (
    extract_ratings_from_omdb,
    search_omdb_by_imdb_id,
    search_omdb_with_candidates,
)
from backend.plex_client import (
    get_best_search_title,
    get_imdb_id_from_movie,
    get_movie_file_info,
)
from backend.scoring import decide_action
from backend.wiki_client import find_movie_in_wikidata


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

    # ----------------------------------------------------
    # 1) ID IMDb inicial (Plex: todos los GUID posibles)
    # ----------------------------------------------------
    imdb_id = get_imdb_id_from_movie(movie)

    # ----------------------------------------------------
    # 2) Si Plex no trae imdb_id, intentamos Wikipedia/Wikidata
    # ----------------------------------------------------
    wiki_info: Optional[Dict[str, Any]] = None

    if not imdb_id:
        search_title = get_best_search_title(movie)
        wiki_info = find_movie_in_wikidata(search_title, year, language="en")

        if wiki_info and wiki_info.get("imdb_id"):
            imdb_id = wiki_info["imdb_id"]
            logs.append(
                f"[WIKI] IMDb ID obtenido vía Wikidata para "
                f"'{search_title}' ({year}): {imdb_id} "
                f"(wikidata_id={wiki_info.get('wikidata_id')}, "
                f"wikipedia_title='{wiki_info.get('wikipedia_title')}')"
            )
        elif wiki_info:
            logs.append(
                f"[WIKI] Encontrada página en Wikipedia/Wikidata para "
                f"'{search_title}' ({year}), pero sin imdb_id (wikidata_id={wiki_info.get('wikidata_id')})"
            )

    # ----------------------------------------------------
    # 3) Búsqueda OMDb (priorizando IMDb ID si lo tenemos)
    # ----------------------------------------------------
    if imdb_id:
        omdb_data = search_omdb_by_imdb_id(imdb_id)
    else:
        search_title = get_best_search_title(movie)
        omdb_data = search_omdb_with_candidates(search_title, year)

    # Si OMDb tiene imdbID y difiere / falta, lo usamos para rellenar/corregir.
    if omdb_data:
        omdb_imdb_id = omdb_data.get("imdbID")
        if omdb_imdb_id and omdb_imdb_id != imdb_id:
            logs.append(
                f"[OMDB] imdbID corregido/rellenado desde OMDb: "
                f"{imdb_id} -> {omdb_imdb_id}"
            )
            imdb_id = omdb_imdb_id

    # ----------------------------------------------------
    # 4) Ratings y scoring
    # ----------------------------------------------------
    imdb_rating, imdb_votes, rt_score = extract_ratings_from_omdb(omdb_data)

    # Decisión KEEP/MAYBE/DELETE/UNKNOWN (usando también el año para votos dinámicos / bayes)
    decision, reason = decide_action(imdb_rating, imdb_votes, rt_score, year)

    # ----------------------------------------------------
    # 5) Posible misidentificación
    # ----------------------------------------------------
    misidentified_hint = detect_misidentified(
        title, year, omdb_data, imdb_rating, imdb_votes, rt_score
    )
    if misidentified_hint:
        logs.append(
            f"[MISIDENTIFIED] {library} / {title} ({year}): {misidentified_hint}"
        )

    # ----------------------------------------------------
    # 6) Sugerencias de metadata
    # ----------------------------------------------------
    meta_sugg = generate_metadata_suggestions_row(movie, omdb_data)
    if meta_sugg:
        logs.append(
            f"[METADATA_SUGG] {library} / {title} ({year}): "
            f"{meta_sugg.get('suggestions_json')}"
        )

    # ----------------------------------------------------
    # 7) Extras OMDb (poster y trailer si existiera)
    # ----------------------------------------------------
    poster_url = None
    trailer_url = None
    if omdb_data:
        poster_url = omdb_data.get("Poster")
        # Si en el futuro quisieras trailer_url de otro sitio, se rellenaría aquí.

    # ----------------------------------------------------
    # 8) Construcción de la fila para *_all.csv
    # ----------------------------------------------------
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
        "omdb_json": json.dumps(omdb_data, ensure_ascii=False) if omdb_data else None,
        # Campos opcionales de depuración sobre Wikipedia/Wikidata
        "wiki_imdb_id": wiki_info.get("imdb_id") if wiki_info else None,
        "wikidata_id": wiki_info.get("wikidata_id") if wiki_info else None,
        "wikipedia_title": wiki_info.get("wikipedia_title") if wiki_info else None,
    }

    return row, meta_sugg, logs