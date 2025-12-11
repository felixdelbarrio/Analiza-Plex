from typing import Any, Dict, Optional, Tuple

from backend.config import (
    IMDB_KEEP_MIN_RATING,
    IMDB_KEEP_MIN_RATING_WITH_RT,
    IMDB_KEEP_MIN_VOTES,
    IMDB_DELETE_MAX_RATING,
    IMDB_DELETE_MAX_VOTES,
    IMDB_DELETE_MAX_VOTES_NO_RT,
    RT_KEEP_MIN_SCORE,
)


def compute_scoring(
    imdb_rating: Optional[float],
    imdb_votes: Optional[int],
    rt_score: Optional[int],
) -> Dict[str, Any]:
    """
    Calcula la decisión de KEEP / DELETE / MAYBE / UNKNOWN y devuelve
    un objeto de scoring más rico que decide_action, incluyendo:

      - decision: str
      - reason: str
      - rule: str   (identificador interno de la regla aplicada)
      - inputs: dict con imdb_rating, imdb_votes, rt_score

    Esta función NO cambia la lógica de decisión previa: reproduce exactamente
    las mismas condiciones que se usaban en decide_action.
    """
    inputs = {
        "imdb_rating": imdb_rating,
        "imdb_votes": imdb_votes,
        "rt_score": rt_score,
    }

    # Caso sin datos suficientes
    if imdb_rating is None and imdb_votes is None and rt_score is None:
        return {
            "decision": "UNKNOWN",
            "reason": "Sin datos suficientes de OMDb",
            "rule": "NO_DATA",
            "inputs": inputs,
        }

    # Regla KEEP por IMDB (rating + votos)
    if imdb_rating is not None and imdb_votes is not None:
        if imdb_rating >= IMDB_KEEP_MIN_RATING and imdb_votes >= IMDB_KEEP_MIN_VOTES:
            return {
                "decision": "KEEP",
                "reason": (
                    f"imdbRating={imdb_rating} imdbVotes={imdb_votes} "
                    f"cumple umbrales KEEP"
                ),
                "rule": "KEEP_IMDB",
                "inputs": inputs,
            }

    # Regla KEEP por RT + IMDB
    if rt_score is not None and imdb_rating is not None:
        if rt_score >= RT_KEEP_MIN_SCORE and imdb_rating >= IMDB_KEEP_MIN_RATING_WITH_RT:
            return {
                "decision": "KEEP",
                "reason": (
                    f"RT={rt_score}% y imdbRating={imdb_rating} "
                    f"cumplen umbrales KEEP"
                ),
                "rule": "KEEP_RT_IMDB",
                "inputs": inputs,
            }

    # Regla DELETE por IMDB (rating bajo + pocos votos)
    if imdb_rating is not None and imdb_votes is not None:
        if imdb_rating <= IMDB_DELETE_MAX_RATING and imdb_votes <= IMDB_DELETE_MAX_VOTES:
            return {
                "decision": "DELETE",
                "reason": (
                    f"imdbRating={imdb_rating} imdbVotes={imdb_votes} "
                    f"cumplen umbrales DELETE"
                ),
                "rule": "DELETE_IMDB",
                "inputs": inputs,
            }

    # Regla DELETE sin RT: umbral de votos algo distinto
    if (
        imdb_rating is not None
        and imdb_votes is not None
        and rt_score is None
        and imdb_rating <= IMDB_DELETE_MAX_RATING
        and imdb_votes <= IMDB_DELETE_MAX_VOTES_NO_RT
    ):
        return {
            "decision": "DELETE",
            "reason": (
                f"imdbRating={imdb_rating} imdbVotes={imdb_votes} "
                f"sin RT y cumple umbrales DELETE"
            ),
            "rule": "DELETE_IMDB_NO_RT",
            "inputs": inputs,
        }

    # Si no entra en KEEP/DELETE, lo dejamos como MAYBE
    return {
        "decision": "MAYBE",
        "reason": "No cumple claramente KEEP ni DELETE",
        "rule": "FALLBACK_MAYBE",
        "inputs": inputs,
    }


def decide_action(
    imdb_rating: Optional[float],
    imdb_votes: Optional[int],
    rt_score: Optional[int],
) -> Tuple[str, str]:
    """
    Devuelve (decision, reason) en función de los umbrales configurados.
    Posibles decisiones: KEEP, DELETE, MAYBE, UNKNOWN.

    Esta función mantiene la API histórica y se apoya en compute_scoring
    para la lógica interna.
    """
    result = compute_scoring(imdb_rating, imdb_votes, rt_score)
    return result["decision"], result["reason"]