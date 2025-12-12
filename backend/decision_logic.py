"""Lógica de heurística para detectar posibles películas mal identificadas.

Funciones públicas:
- detect_misidentified(...): devuelve una cadena con pistas ('' si no hay).
- sort_filtered_rows(rows): ordena filas según reglas de prioridad.
"""

from typing import Optional, Dict, Any, List
import difflib
import re

from backend import logger as _logger
from backend.omdb_client import extract_year_from_omdb
from backend.config import (
    IMDB_MIN_VOTES_FOR_KNOWN,
    IMDB_RATING_LOW_THRESHOLD,
    RT_RATING_LOW_THRESHOLD,
)


TITLE_SIMILARITY_THRESHOLD = 0.60


def _normalize_title(s: Optional[str]) -> str:
    if not s:
        return ""
    # Lowercase, remove punctuation, collapse whitespace
    s2 = s.lower()
    s2 = re.sub(r"[^a-z0-9\s]", " ", s2)
    s2 = re.sub(r"\s+", " ", s2).strip()
    return s2


def detect_misidentified(
    plex_title: Optional[str],
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

    pt = _normalize_title(plex_title)
    ot = _normalize_title(omdb_title)

    # -----------------------------
    # 1) Títulos claramente distintos
    # -----------------------------
    if pt and ot:
        # Si uno contiene al otro, probablemente están relacionados
        if pt != ot and pt not in ot and ot not in pt:
            # Comprobación de similaridad más suave
            sim = difflib.SequenceMatcher(a=pt, b=ot).ratio()
            if sim < TITLE_SIMILARITY_THRESHOLD:
                hints.append(f"Title mismatch: Plex='{plex_title}' vs OMDb='{omdb_title}' (sim={sim:.2f})")
                _logger.debug(f"Title similarity for '{plex_title}' vs '{omdb_title}': {sim:.2f}")

    # -----------------------------
    # 2) Años muy diferentes (> 1)
    # -----------------------------
    try:
        if plex_year is not None and omdb_year is not None:
            if abs(int(plex_year) - int(omdb_year)) > 1:
                hints.append(f"Year mismatch: Plex={plex_year}, OMDb={omdb_year}")
    except Exception:
        # Si la conversión falla, no añadimos hint pero lo logueamos
        _logger.debug(f"Could not compare years: plex_year={plex_year}, omdb_year={omdb_year}")

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