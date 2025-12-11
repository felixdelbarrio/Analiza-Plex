from typing import Any, Dict, Optional, Tuple

from backend.config import (
    IMDB_KEEP_MIN_RATING,
    IMDB_KEEP_MIN_RATING_WITH_RT,
    RT_KEEP_MIN_SCORE,
    IMDB_DELETE_MAX_RATING,
    IMDB_DELETE_MAX_VOTES,
    IMDB_DELETE_MAX_VOTES_NO_RT,
    ENABLE_BAYESIAN_SCORING,
    BAYES_GLOBAL_MEAN_DEFAULT,
    BAYES_DELETE_MAX_SCORE,
    get_votes_threshold_for_year,
)


def _compute_bayes_score(
    imdb_rating: Optional[float],
    imdb_votes: Optional[int],
    m: int,
    c_global: float,
) -> Optional[float]:
    """
    score_bayes = (v / (v + m)) * R + (m / (v + m)) * C

      - R: imdb_rating
      - v: imdb_votes
      - m: número mínimo de votos (según antigüedad)
      - C: media global (BAYES_GLOBAL_MEAN_DEFAULT o la que uses)

    Devuelve None si no se puede calcular.
    """
    if imdb_rating is None or imdb_votes is None:
        return None

    try:
        v = int(imdb_votes)
        if v < 0:
            return None
    except (TypeError, ValueError):
        return None

    if m < 0:
        m = 0

    if v + m == 0:
        return None

    return (v / (v + m)) * float(imdb_rating) + (m / (v + m)) * float(c_global)


def compute_scoring(
    imdb_rating: Optional[float],
    imdb_votes: Optional[int],
    rt_score: Optional[int],
    year: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Calcula la decisión de KEEP / DELETE / MAYBE / UNKNOWN y devuelve
    un objeto de scoring enriquecido que incluye:

      - decision: str
      - reason: str
      - rule: str   (identificador interno de la regla aplicada)
      - inputs: dict con imdb_rating, imdb_votes, rt_score, year

    Ajustes importantes:
      - El número mínimo de votos exigidos para KEEP depende de la antigüedad
        de la película (IMDB_VOTES_BY_YEAR).
      - Opcionalmente, se puede activar un scoring bayesiano para DELETE
        (ENABLE_BAYESIAN_SCORING) usando:

          score_bayes = (v / (v + m)) * R + (m / (v + m)) * C

        y comparándolo con BAYES_DELETE_MAX_SCORE.
      - Además, hay una regla explícita de DELETE cuando el rating es bajo
        pero hay muchos votos para su año (consenso fuerte en que es mala).

    NOTA: el parámetro year es opcional para mantener compatibilidad
    con llamadas antiguas que solo pasan (rating, votos, rt_score).
    """
    inputs: Dict[str, Any] = {
        "imdb_rating": imdb_rating,
        "imdb_votes": imdb_votes,
        "rt_score": rt_score,
        "year": year,
    }

    # ----------------------------------------------------
    # Caso sin datos suficientes
    # ----------------------------------------------------
    if imdb_rating is None and imdb_votes is None and rt_score is None:
        return {
            "decision": "UNKNOWN",
            "reason": "Sin datos suficientes de OMDb",
            "rule": "NO_DATA",
            "inputs": inputs,
        }

    # ----------------------------------------------------
    # Regla KEEP por IMDb (rating + votos dinámicos por año)
    # ----------------------------------------------------
    if imdb_rating is not None and imdb_votes is not None:
        dynamic_votes_needed = get_votes_threshold_for_year(year)

        if (
            dynamic_votes_needed > 0
            and imdb_rating >= IMDB_KEEP_MIN_RATING
            and imdb_votes >= dynamic_votes_needed
        ):
            return {
                "decision": "KEEP",
                "reason": (
                    f"imdbRating={imdb_rating} con imdbVotes={imdb_votes} "
                    f"≥ mínimo dinámico {dynamic_votes_needed}"
                ),
                "rule": "KEEP_IMDB_DYNAMIC_VOTES",
                "inputs": inputs,
            }

    # ----------------------------------------------------
    # Regla KEEP por RT + IMDb
    # ----------------------------------------------------
    if rt_score is not None and imdb_rating is not None:
        if rt_score >= RT_KEEP_MIN_SCORE and imdb_rating >= IMDB_KEEP_MIN_RATING_WITH_RT:
            return {
                "decision": "KEEP",
                "reason": (
                    f"RT={rt_score}% y imdbRating={imdb_rating} "
                    f"cumplen umbrales KEEP (RT + IMDb)"
                ),
                "rule": "KEEP_RT_IMDB",
                "inputs": inputs,
            }

    # ----------------------------------------------------
    # Regla DELETE bayesiana (opcional)  [Opción A]
    # ----------------------------------------------------
    if ENABLE_BAYESIAN_SCORING and imdb_rating is not None and imdb_votes is not None:
        m_dynamic = get_votes_threshold_for_year(year)
        bayes_score = _compute_bayes_score(
            imdb_rating=imdb_rating,
            imdb_votes=imdb_votes,
            m=m_dynamic,
            c_global=BAYES_GLOBAL_MEAN_DEFAULT,
        )

        if bayes_score is not None and bayes_score <= BAYES_DELETE_MAX_SCORE:
            return {
                "decision": "DELETE",
                "reason": (
                    f"score_bayes={bayes_score:.2f} ≤ BAYES_DELETE_MAX_SCORE={BAYES_DELETE_MAX_SCORE} "
                    f"(R={imdb_rating}, v={imdb_votes}, m={m_dynamic}, C={BAYES_GLOBAL_MEAN_DEFAULT})"
                ),
                "rule": "DELETE_BAYES",
                "inputs": {
                    **inputs,
                    "score_bayes": bayes_score,
                    "m_dynamic": m_dynamic,
                },
            }

    # ----------------------------------------------------
    # Regla DELETE explícita: rating bajo + muchos votos  [Opción B]
    #  - Captura pelis con consenso fuerte de que son malas:
    #    rating bajo y muchos votos para su antigüedad.
    #  - Solo se aplica si tenemos un mínimo dinámico > 0 para ese año.
    # ----------------------------------------------------
    if imdb_rating is not None and imdb_votes is not None:
        dynamic_votes_needed = get_votes_threshold_for_year(year)

        if (
            dynamic_votes_needed > 0
            and imdb_rating <= IMDB_DELETE_MAX_RATING
            and imdb_votes >= dynamic_votes_needed
        ):
            return {
                "decision": "DELETE",
                "reason": (
                    "Rating IMDb bajo pero con muchos votos para su antigüedad; "
                    f"imdbRating={imdb_rating}, imdbVotes={imdb_votes}, "
                    f"mínimo por año={dynamic_votes_needed}"
                ),
                "rule": "DELETE_LOW_RATING_HIGH_VOTES",
                "inputs": inputs,
            }

    # ----------------------------------------------------
    # Regla DELETE por IMDb (rating bajo + pocos votos)
    #   (solo si bayesiano / regla explícita no han decidido antes)
    # ----------------------------------------------------
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

    # ----------------------------------------------------
    # Regla DELETE sin RT: umbral de votos algo distinto
    # ----------------------------------------------------
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

    # ----------------------------------------------------
    # Fallback: MAYBE
    # ----------------------------------------------------
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
    year: Optional[int] = None,
) -> Tuple[str, str]:
    """
    Devuelve (decision, reason) en función de los umbrales configurados.

    year es opcional para mantener compatibilidad con llamadas antiguas
    que solo pasan (rating, votos, rt_score). Si es None, se usará el
    umbral de votos dinámico por defecto (get_votes_threshold_for_year
    ya gestiona el caso None).
    """
    result = compute_scoring(imdb_rating, imdb_votes, rt_score, year)
    return result["decision"], result["reason"]