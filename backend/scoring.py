# backend/scoring.py
from typing import Any, Dict, Optional, Tuple

from backend.config import (
    BAYES_DELETE_MAX_SCORE,
    IMDB_DELETE_MAX_VOTES,
    IMDB_DELETE_MAX_VOTES_NO_RT,
    IMDB_KEEP_MIN_RATING_WITH_RT,
    RT_KEEP_MIN_SCORE,
    get_votes_threshold_for_year,
)
from backend.stats import (
    get_global_imdb_mean_from_cache,
    get_auto_keep_rating_threshold,
    get_auto_delete_rating_threshold,
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
      - C: media global (derivada de omdb_cache o BAYES_GLOBAL_MEAN_DEFAULT)

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
      - El umbral de rating para KEEP/DELETE se auto-ajusta desde omdb_cache
        vía get_auto_keep_rating_threshold() / get_auto_delete_rating_threshold(),
        con fallback a los valores de config si no hay datos suficientes.
      - Se aplica un scoring bayesiano para DELETE comparando con BAYES_DELETE_MAX_SCORE.
      - Hay una regla explícita de DELETE cuando el rating es bajo pero hay muchos votos.
    """
    inputs: Dict[str, Any] = {
        "imdb_rating": imdb_rating,
        "imdb_votes": imdb_votes,
        "rt_score": rt_score,
        "year": year,
    }

    # Caso sin datos suficientes
    if imdb_rating is None and imdb_votes is None and rt_score is None:
        return {
            "decision": "UNKNOWN",
            "reason": "Sin datos suficientes de OMDb",
            "rule": "NO_DATA",
            "inputs": inputs,
        }

    # Umbrales dinámicos de rating (KEEP / DELETE) basados en estadísticas
    keep_rating_threshold = get_auto_keep_rating_threshold()
    delete_rating_threshold = get_auto_delete_rating_threshold()

    # ----------------------------------------------------
    # Regla KEEP por IMDb (rating + votos dinámicos por año)
    # ----------------------------------------------------
    if imdb_rating is not None and imdb_votes is not None:
        dynamic_votes_needed = get_votes_threshold_for_year(year)

        if (
            dynamic_votes_needed > 0
            and imdb_rating >= keep_rating_threshold
            and imdb_votes >= dynamic_votes_needed
        ):
            return {
                "decision": "KEEP",
                "reason": (
                    f"imdbRating={imdb_rating} ≥ umbral KEEP={keep_rating_threshold:.2f} "
                    f"y imdbVotes={imdb_votes} ≥ mínimo dinámico {dynamic_votes_needed}"
                ),
                "rule": "KEEP_IMDB_DYNAMIC_VOTES",
                "inputs": {
                    **inputs,
                    "keep_rating_threshold": keep_rating_threshold,
                    "dynamic_votes_needed": dynamic_votes_needed,
                },
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
    # Regla DELETE bayesiana (siempre activa)
    # ----------------------------------------------------
    if imdb_rating is not None and imdb_votes is not None:
        m_dynamic = get_votes_threshold_for_year(year)
        c_global = get_global_imdb_mean_from_cache()

        bayes_score = _compute_bayes_score(
            imdb_rating=imdb_rating,
            imdb_votes=imdb_votes,
            m=m_dynamic,
            c_global=c_global,
        )

        if bayes_score is not None and bayes_score <= BAYES_DELETE_MAX_SCORE:
            return {
                "decision": "DELETE",
                "reason": (
                    f"score_bayes={bayes_score:.2f} ≤ BAYES_DELETE_MAX_SCORE={BAYES_DELETE_MAX_SCORE} "
                    f"(R={imdb_rating}, v={imdb_votes}, m={m_dynamic}, C={c_global:.2f})"
                ),
                "rule": "DELETE_BAYES",
                "inputs": {
                    **inputs,
                    "score_bayes": bayes_score,
                    "m_dynamic": m_dynamic,
                    "c_global": c_global,
                },
            }

    # ----------------------------------------------------
    # Regla DELETE explícita: rating bajo + muchos votos  [Opción B]
    # ----------------------------------------------------
    if imdb_rating is not None and imdb_votes is not None:
        dynamic_votes_needed = get_votes_threshold_for_year(year)

        if (
            dynamic_votes_needed > 0
            and imdb_rating <= delete_rating_threshold
            and imdb_votes >= dynamic_votes_needed
        ):
            return {
                "decision": "DELETE",
                "reason": (
                    "Rating IMDb bajo pero con muchos votos para su antigüedad; "
                    f"imdbRating={imdb_rating} ≤ umbral DELETE={delete_rating_threshold:.2f}, "
                    f"imdbVotes={imdb_votes} ≥ mínimo por año={dynamic_votes_needed}"
                ),
                "rule": "DELETE_LOW_RATING_HIGH_VOTES",
                "inputs": {
                    **inputs,
                    "delete_rating_threshold": delete_rating_threshold,
                    "dynamic_votes_needed": dynamic_votes_needed,
                },
            }

    # ----------------------------------------------------
    # Regla DELETE por IMDb (rating bajo + pocos votos)
    #   (solo si lo anterior no ha decidido antes)
    # ----------------------------------------------------
    if imdb_rating is not None and imdb_votes is not None:
        if imdb_rating <= delete_rating_threshold and imdb_votes <= IMDB_DELETE_MAX_VOTES:
            return {
                "decision": "DELETE",
                "reason": (
                    f"imdbRating={imdb_rating} ≤ umbral DELETE={delete_rating_threshold:.2f} "
                    f"e imdbVotes={imdb_votes} ≤ IMDB_DELETE_MAX_VOTES={IMDB_DELETE_MAX_VOTES}"
                ),
                "rule": "DELETE_IMDB",
                "inputs": {
                    **inputs,
                    "delete_rating_threshold": delete_rating_threshold,
                },
            }

    # ----------------------------------------------------
    # Regla DELETE sin RT: umbral de votos algo distinto
    # ----------------------------------------------------
    if (
        imdb_rating is not None
        and imdb_votes is not None
        and rt_score is None
        and imdb_rating <= delete_rating_threshold
        and imdb_votes <= IMDB_DELETE_MAX_VOTES_NO_RT
    ):
        return {
            "decision": "DELETE",
            "reason": (
                f"imdbRating={imdb_rating} ≤ umbral DELETE={delete_rating_threshold:.2f} "
                f"sin RT y imdbVotes={imdb_votes} ≤ IMDB_DELETE_MAX_VOTES_NO_RT={IMDB_DELETE_MAX_VOTES_NO_RT}"
            ),
            "rule": "DELETE_IMDB_NO_RT",
            "inputs": {
                **inputs,
                "delete_rating_threshold": delete_rating_threshold,
            },
        }

    # ----------------------------------------------------
    # Fallback: MAYBE (con razón más explícita)
    # ----------------------------------------------------
    return {
        "decision": "MAYBE",
        "reason": (
            "No cumple claramente KEEP ni DELETE según umbrales dinámicos de rating/votos; "
            f"R={imdb_rating}, v={imdb_votes}, RT={rt_score}, "
            f"keep_thr≈{keep_rating_threshold:.2f}, delete_thr≈{delete_rating_threshold:.2f}"
        ),
        "rule": "FALLBACK_MAYBE",
        "inputs": {
            **inputs,
            "keep_rating_threshold": keep_rating_threshold,
            "delete_rating_threshold": delete_rating_threshold,
        },
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