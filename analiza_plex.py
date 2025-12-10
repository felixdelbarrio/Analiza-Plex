import json
from typing import Optional, Dict, Any, List, Tuple

from backend.config import (
    OUTPUT_PREFIX,
    EXCLUDE_LIBRARIES,
    METADATA_OUTPUT_PREFIX,
    SILENT_MODE,
)
from backend.plex_client import (
    connect_plex,
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
    decide_action,
    detect_misidentified,
    sort_filtered_rows,
)
from backend.scoring import compute_scoring
from backend.reporting import (
    write_all_csv,
    write_filtered_csv,
    write_suggestions_csv,
)
from backend.metadata_fix import (
    generate_metadata_suggestions_row,
    apply_metadata_suggestion,
)


# ============================================================
#                analyze_single_movie
# ============================================================


def analyze_single_movie(
    movie,
) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]], List[str]]:
    """
    Analiza una película individual de Plex.

    Devuelve:
      - row: dict con la información principal (para *_all.csv)
      - meta_sugg: dict con sugerencia de metadata (o None)
      - logs: lista de strings para el fichero de log de metadata
    """
    logs: List[str] = []

    library = getattr(movie, "librarySectionTitle", None)
    title = getattr(movie, "title", None)
    year = getattr(movie, "year", None)
    plex_rating = getattr(movie, "rating", None)
    rating_key = getattr(movie, "ratingKey", None)
    guid = getattr(movie, "guid", None)
    thumb = getattr(movie, "thumb", None)

    file_path, file_size = get_movie_file_info(movie)

    imdb_id = get_imdb_id_from_plex_guid(guid or "")

    omdb_data: Optional[Dict[str, Any]] = None

    if imdb_id:
        omdb_data = search_omdb_by_imdb_id(imdb_id)
    else:
        search_title = get_best_search_title(movie)
        omdb_data = search_omdb_with_candidates(search_title, year)

    imdb_rating, imdb_votes, rt_score = extract_ratings_from_omdb(omdb_data)

    # --------------------------------------------------------
    # Scoring enriquecido: usamos compute_scoring
    # --------------------------------------------------------
    scoring = compute_scoring(imdb_rating, imdb_votes, rt_score)
    decision = scoring["decision"]
    reason = scoring["reason"]
    scoring_rule = scoring.get("rule")

    misidentified_hint = detect_misidentified(
        title, year, omdb_data, imdb_rating, imdb_votes, rt_score
    )

    if misidentified_hint:
        logs.append(
            f"[MISIDENTIFIED] {library} / {title} ({year}): {misidentified_hint}"
        )

    meta_sugg = generate_metadata_suggestions_row(movie, omdb_data)
    if meta_sugg:
        logs.append(
            f"[METADATA_SUGG] {library} / {title} ({year}): "
            f"{meta_sugg.get('suggestions_json')}"
        )

    poster_url = None
    trailer_url = None

    if omdb_data:
        poster_url = omdb_data.get("Poster")
        trailer_url = None

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
        "scoring_rule": scoring_rule,
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


# ============================================================
#        BARRA DE PROGRESO EN CONSOLA (SILENT_MODE=True)
# ============================================================


def update_progress_bar(current: int, total: int, library_title: str) -> None:
    """
    Muestra una barra de progreso en una sola línea.
    Solo se usa cuando SILENT_MODE=True.
    """
    if not SILENT_MODE or total <= 0:
        return

    bar_length = 40
    fraction = current / total
    filled = int(bar_length * fraction)
    bar = "#" * filled + "-" * (bar_length - filled)
    percent = int(fraction * 100)

    msg = f"[{bar}] {percent:3d}% ({current}/{total}) Biblioteca: {library_title}"
    # Sobrescribimos la línea anterior
    print(msg.ljust(100), end="\r", flush=True)


# ============================================================
#                        MAIN ANALYSIS
# ============================================================


def analyze_all_libraries():
    plex = connect_plex()

    libraries = []
    for section in plex.library.sections():
        if section.type != "movie":
            continue
        if section.title in EXCLUDE_LIBRARIES:
            print(f"Saltando biblioteca excluida: {section.title}")
            continue
        libraries.append(section)

    print("Bibliotecas a analizar:", [lib.title for lib in libraries])

    all_rows: List[Dict[str, Any]] = []
    metadata_suggestions: List[Dict[str, Any]] = []
    logs: List[str] = []

    for lib in libraries:
        print(f"Analizando biblioteca: {lib.title}")
        try:
            movies = lib.all()
        except Exception as e:
            print(f"ERROR al obtener películas de {lib.title}: {e}")
            continue

        total_movies = len(movies)

        for idx, movie in enumerate(movies, start=1):
            # Barra de progreso solo si SILENT_MODE=True
            update_progress_bar(idx, total_movies, lib.title)

            try:
                row, meta_sugg, log_lines = analyze_single_movie(movie)
                if row:
                    all_rows.append(row)
                if meta_sugg:
                    metadata_suggestions.append(meta_sugg)
                logs.extend(log_lines)
            except Exception as e:
                print(
                    f"ERROR analizando película '{getattr(movie, 'title', '???')}': {e}"
                )

        # Al terminar una biblioteca, dejamos la barra "fija" y saltamos de línea
        if SILENT_MODE and total_movies > 0:
            print()  # newline para no sobreescribir la barra final

    if all_rows:
        filtered = [
            r for r in all_rows if r.get("decision") in ("DELETE", "MAYBE")
        ]
        filtered = sort_filtered_rows(filtered)
    else:
        filtered = []

    all_csv = f"{OUTPUT_PREFIX}_all.csv"
    filtered_csv = f"{OUTPUT_PREFIX}_filtered.csv"

    write_all_csv(all_csv, all_rows)
    write_filtered_csv(filtered_csv, filtered)

    if metadata_suggestions:
        sugg_csv = f"{METADATA_OUTPUT_PREFIX}_suggestions.csv"
        write_suggestions_csv(sugg_csv, metadata_suggestions)

    log_path = f"{METADATA_OUTPUT_PREFIX}_log.txt"
    with open(log_path, "w", encoding="utf-8") as f:
        for line in logs:
            f.write(line + "\n")
    print(f"Log de corrección metadata: {log_path}")


# ============================================================
#                        MAIN
# ============================================================

if __name__ == "__main__":
    analyze_all_libraries()