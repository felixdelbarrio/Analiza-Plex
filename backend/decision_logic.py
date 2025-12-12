# backend/decision_logic.py
from typing import Optional, Dict, Any, List

from backend.omdb_client import extract_year_from_omdb
from backend.config import (
    IMDB_MIN_VOTES_FOR_KNOWN,
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

    Criterios:
      - Título Plex vs Título OMDb muy distintos.
      - Año Plex vs Año OMDb separados > 1 año.
      - IMDb muy baja con bastantes votos (posible "otra" peli).
      - Rotten Tomatoes muy bajo con bastantes votos.
    """
    if not omdb_data:
        return ""

    hints: List[str] = []

    omdb_title = omdb_data.get("Title") or ""
    omdb_year = extract_year_from_omdb(omdb_data)

    pt = (plex_title or "").strip().lower()
    ot = (omdb_title or "").strip().lower()

    # -----------------------------
    # 1) Títulos claramente distintos
    # -----------------------------
    if pt and ot:
        # Versión rápida: no iguales y uno no contiene al otro
        if pt != ot and pt not in ot and ot not in pt:
            hints.append(f"Title mismatch: Plex='{plex_title}' vs OMDb='{omdb_title}'")

    # -----------------------------
    # 2) Años muy diferentes (> 1)
    # -----------------------------
    if plex_year and omdb_year:
        if abs(plex_year - omdb_year) > 1:
            hints.append(f"Year mismatch: Plex={plex_year}, OMDb={omdb_year}")

    # -----------------------------
    # 3) IMDb muy baja con suficientes votos
    # -----------------------------
    votes = imdb_votes or 0
    if (
        imdb_rating is not None
        and imdb_rating <= IMDB_RATING_LOW_THRESHOLD
        and votes >= IMDB_MIN_VOTES_FOR_KNOWN
    ):
        hints.append(
            f"IMDb muy baja ({imdb_rating:.1f} ≤ {IMDB_RATING_LOW_THRESHOLD}) "
            f"con bastantes votos ({votes} ≥ {IMDB_MIN_VOTES_FOR_KNOWN}). Revisar identificación."
        )

    # -----------------------------
    # 4) RT muy bajo con suficientes votos
    # -----------------------------
    if (
        rt_score is not None
        and rt_score <= RT_RATING_LOW_THRESHOLD
        and votes >= IMDB_MIN_VOTES_FOR_KNOWN
    ):
        hints.append(
            f"RT muy bajo ({rt_score}% ≤ {RT_RATING_LOW_THRESHOLD}%) "
            f"para una peli aparentemente conocida ({votes} votos IMDb)."
        )

    return " | ".join(hints)


def sort_filtered_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Ordena las filas filtradas para el CSV final, priorizando:
      1) DELETE primero, luego MAYBE, luego KEEP, luego UNKNOWN.
      2) Más votos IMDb (las más relevantes/seguras antes).
      3) Mayor rating IMDb.
      4) Mayor tamaño de fichero (más espacio a liberar primero).
    """

    def key_func(r: Dict[str, Any]):
        decision = r.get("decision") or "UNKNOWN"
        imdb_votes = r.get("imdb_votes") or 0
        imdb_rating = r.get("imdb_rating") or 0.0
        file_size = r.get("file_size") or 0

        decision_rank = {"DELETE": 0, "MAYBE": 1, "KEEP": 2, "UNKNOWN": 3}.get(
            decision, 3
        )
        # Negativos para ordenar de mayor a menor en votes/rating/size
        return (decision_rank, -imdb_votes, -imdb_rating, -file_size)

    return sorted(rows, key=key_func)