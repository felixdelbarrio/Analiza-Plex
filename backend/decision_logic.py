from typing import Optional, Dict, Any, List

from backend.omdb_client import extract_year_from_omdb

from backend.config import (
    IMDB_DELETE_MAX_VOTES_NO_RT,
    IMDB_RATING_LOW_THRESHOLD, 
    RT_RATING_LOW_THRESHOLD,
)

def detect_misidentified(
    plex_title: str,
    plex_year: Optional[int],
    omdb_data: Optional[Dict[str, Any]],
    imdb_rating: Optional[float],
    imdb_votes: Optional[int],
    rt_score: Optional[int],
) -> str:
    """
    Devuelve un texto con pistas de posible identificación errónea,
    o cadena vacía si no hay sospechas.
    """
    if not omdb_data:
        return ""

    hints: List[str] = []

    omdb_title = omdb_data.get("Title") or ""
    omdb_year = extract_year_from_omdb(omdb_data)

    pt = (plex_title or "").strip().lower()
    ot = (omdb_title or "").strip().lower()

    # Títulos claramente distintos
    if pt and ot and pt != ot and pt not in ot and ot not in pt:
        hints.append(f"Title mismatch: Plex='{plex_title}' vs OMDb='{omdb_title}'")

    # Años muy diferentes
    if plex_year and omdb_year and plex_year != omdb_year:
        if abs(plex_year - omdb_year) > 1:
            hints.append(f"Year mismatch: Plex={plex_year}, OMDb={omdb_year}")

    # Rating muy bajo con muchos votos
    if imdb_rating is not None and imdb_rating < IMDB_RATING_LOW_THRESHOLD and (imdb_votes or 0) > IMDB_DELETE_MAX_VOTES_NO_RT:
        hints.append(
            "IMDB rating muy bajo para tantos votos, comprobar identificación."
        )

    # RT muy bajo con muchos votos
    if rt_score is not None and rt_score < RT_RATING_LOW_THRESHOLD and (imdb_votes or 0) > IMDB_DELETE_MAX_VOTES_NO_RT:
        hints.append("RT score muy bajo para película aparentemente conocida.")

    return " | ".join(hints)


def sort_filtered_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Ordena las filas filtradas para el CSV final, priorizando:
      1) DELETE primero, luego MAYBE, luego KEEP, luego UNKNOWN.
      2) Más votos IMDB.
      3) Mayor rating IMDB.
      4) Tamaño de fichero.
    """
    def key_func(r: Dict[str, Any]):
        decision = r.get("decision") or "UNKNOWN"
        imdb_votes = r.get("imdb_votes") or 0
        imdb_rating = r.get("imdb_rating") or 0.0
        file_size = r.get("file_size") or 0

        decision_rank = {"DELETE": 0, "MAYBE": 1, "KEEP": 2, "UNKNOWN": 3}.get(
            decision, 3
        )
        return (decision_rank, imdb_votes, imdb_rating, file_size)

    return sorted(rows, key=key_func)