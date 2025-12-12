# analiza_plex.py
from typing import Dict, Any, List

from backend.config import (
    OUTPUT_PREFIX,
    EXCLUDE_LIBRARIES,
    METADATA_OUTPUT_PREFIX,
    SILENT_MODE,
)
from backend.plex_client import connect_plex
from backend.decision_logic import sort_filtered_rows
from backend.reporting import (
    write_all_csv,
    write_filtered_csv,
    write_suggestions_csv,
)
from backend.analyzer import analyze_single_movie
from backend.wiki_client import set_wiki_progress


# ============================================================
#        PROGRESO SIMPLE POR CONSOLA
# ============================================================


def update_progress(
    current: int,
    total: int,
    library_title: str,
    movie_title: str,
) -> None:
    """
    Muestra una línea simple de progreso de película:
      (x/total) Biblioteca: Título

    Solo se imprime cuando SILENT_MODE=False.
    """
    if SILENT_MODE or total <= 0:
        return

    print(f"({current}/{total}) {library_title}: {movie_title}")


# ============================================================
#                        MAIN ANALYSIS
# ============================================================


def analyze_all_libraries():
    plex = connect_plex()

    # Filtramos solo bibliotecas de películas y no excluidas
    libraries = [
        section
        for section in plex.library.sections()
        if section.type == "movie" and section.title not in EXCLUDE_LIBRARIES
    ]

    total_libs = len(libraries)
    if total_libs == 0:
        print("No hay bibliotecas de películas para analizar (o todas excluidas).")
        return

    # Siempre mostramos el listado de bibliotecas a analizar
    print(
        "Bibliotecas a analizar:",
        [lib.title for lib in libraries],
    )

    all_rows: List[Dict[str, Any]] = []
    metadata_suggestions: List[Dict[str, Any]] = []
    logs: List[str] = []

    for lib_idx, lib in enumerate(libraries, start=1):
        # Este mensaje SIEMPRE sale, independientemente de SILENT_MODE
        print(f"Analizando biblioteca {lib_idx}/{total_libs}: {lib.title}")

        try:
            movies = lib.all()
        except Exception as e:
            print(f"ERROR al obtener películas de {lib.title}: {e}")
            continue

        total_movies = len(movies)
        if total_movies == 0:
            # Nada que hacer en esta biblioteca
            continue

        for idx, movie in enumerate(movies, start=1):
            movie_title = getattr(movie, "title", "???")

            # Progreso simple por consola (solo si SILENT_MODE=False)
            update_progress(idx, total_movies, lib.title, movie_title)

            # Contexto para que wiki_client pueda prefijar sus logs
            set_wiki_progress(idx, total_movies, lib.title, movie_title)

            try:
                row, meta_sugg, log_lines = analyze_single_movie(movie)
                if row:
                    all_rows.append(row)
                if meta_sugg:
                    metadata_suggestions.append(meta_sugg)
                if log_lines:
                    logs.extend(log_lines)
            except Exception as e:
                print(
                    f"ERROR analizando película '{getattr(movie, 'title', '???')}': {e}"
                )

    # --------------------------------------------------------
    # Construcción de CSVs y logs
    # --------------------------------------------------------
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