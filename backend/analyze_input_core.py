from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

from DNLA_input import DNLAInput


# ---------------------------------------------------------------------------
# Configuración de análisis genérico (equivalente a tus thresholds del .env)
# ---------------------------------------------------------------------------


@dataclass
class AnalysisConfig:
    """
    Thresholds de decisión para KEEP / MAYBE / DELETE, inspirados en
    las variables del .env que usas actualmente para Plex.

    No lee directamente el entorno para no acoplarse a la capa de
    configuración: quien llame a este módulo puede construir el
    AnalysisConfig desde env vars, config, flags CLI, etc.
    """

    imdb_keep_min_rating: float = 7.0
    imdb_keep_min_rating_with_rt: float = 6.5
    rt_keep_min_score: int = 75
    imdb_keep_min_votes: int = 50_000
    imdb_delete_max_rating: float = 6.0
    rt_delete_max_score: int = 50


# ---------------------------------------------------------------------------
# Helpers para parsear OMDb
# ---------------------------------------------------------------------------


def _safe_float(value: Any) -> Optional[float]:
    try:
        if value in (None, "", "N/A"):
            return None
        return float(str(value))
    except (TypeError, ValueError):
        return None


def _safe_int(value: Any) -> Optional[int]:
    try:
        if value in (None, "", "N/A"):
            return None
        s = str(value).replace(",", "")
        return int(s)
    except (TypeError, ValueError):
        return None


def _parse_rt_score(ratings: Any) -> Optional[int]:
    """
    Extrae el score de Rotten Tomatoes de la lista OMDb['Ratings'].
    Espera algo tipo: [{"Source": "Rotten Tomatoes", "Value": "95%"}]
    """
    if not isinstance(ratings, list):
        return None

    for entry in ratings:
        if (
            isinstance(entry, dict)
            and entry.get("Source") == "Rotten Tomatoes"
            and isinstance(entry.get("Value"), str)
        ):
            value = entry["Value"].strip()
            if value.endswith("%"):
                value = value[:-1]
            return _safe_int(value)

    return None


def extract_omdb_fields(
    omdb_data: Mapping[str, Any],
) -> Tuple[Optional[float], Optional[int], Optional[int]]:
    """
    Devuelve tupla (imdb_rating, imdb_votes, rt_score) a partir de
    un dict de OMDb.
    """
    imdb_rating = _safe_float(omdb_data.get("imdbRating"))
    imdb_votes = _safe_int(omdb_data.get("imdbVotes"))
    rt_score = _parse_rt_score(omdb_data.get("Ratings"))

    return imdb_rating, imdb_votes, rt_score


# ---------------------------------------------------------------------------
# Lógica de decisión genérica KEEP / MAYBE / DELETE / UNKNOWN
# ---------------------------------------------------------------------------


def decide_movie(
    imdb_rating: Optional[float],
    imdb_votes: Optional[int],
    rt_score: Optional[int],
    cfg: AnalysisConfig,
) -> Tuple[str, str]:
    """
    Devuelve (decision, reason) usando un conjunto de reglas sencillas
    basadas en IMDb + Rotten Tomatoes.

    No asume Plex ni ningún otro backend; solo trabaja con números.
    """
    # Sin datos útiles → UNKNOWN
    if imdb_rating is None and rt_score is None:
        return "UNKNOWN", "Sin datos de rating en OMDb"

    # Pre-calculamos algunas banderas
    has_enough_votes = (
        imdb_votes is not None and imdb_votes >= cfg.imdb_keep_min_votes
    )
    low_votes = imdb_votes is not None and imdb_votes < cfg.imdb_keep_min_votes

    # 1) Casos con RT disponible
    if rt_score is not None and imdb_rating is not None:
        if has_enough_votes and (
            imdb_rating >= cfg.imdb_keep_min_rating_with_rt
            and rt_score >= cfg.rt_keep_min_score
        ):
            return "KEEP", "Buenas valoraciones IMDb + RT con suficientes votos"

        if (
            imdb_rating <= cfg.imdb_delete_max_rating
            and rt_score <= cfg.rt_delete_max_score
        ):
            return "DELETE", "Malas valoraciones IMDb + RT"

        # Borderline
        if low_votes and imdb_rating >= cfg.imdb_keep_min_rating_with_rt:
            return (
                "MAYBE",
                "Rating alto pero con pocas votaciones (IMDb + RT)",
            )

        return "MAYBE", "Ratings intermedios en IMDb/RT"

    # 2) Solo IMDb
    if imdb_rating is not None:
        if has_enough_votes and imdb_rating >= cfg.imdb_keep_min_rating:
            return "KEEP", "Buena valoración IMDb con suficientes votos"

        if imdb_rating <= cfg.imdb_delete_max_rating:
            return "DELETE", "Mala valoración IMDb"

        if low_votes and imdb_rating >= cfg.imdb_keep_min_rating:
            return (
                "MAYBE",
                "IMDb decente pero con pocas votaciones",
            )

        return "MAYBE", "Valoración IMDb intermedia"

    # 3) Solo RT (raro, pero lo contemplamos)
    if rt_score is not None:
        if rt_score >= cfg.rt_keep_min_score:
            return "KEEP", "Buena valoración en Rotten Tomatoes"
        if rt_score <= cfg.rt_delete_max_score:
            return "DELETE", "Mala valoración en Rotten Tomatoes"
        return "MAYBE", "Valoración RT intermedia"

    # Fallback defensivo
    return "UNKNOWN", "No se pudo determinar decisión a partir de ratings"


# ---------------------------------------------------------------------------
# Núcleo de análisis genérico
# ---------------------------------------------------------------------------

FetchOmdbCallable = Callable[[str, Optional[int]], Mapping[str, Any]]


def analyze_input_movie(
    movie: DNLAInput,
    fetch_omdb: FetchOmdbCallable,
    cfg: Optional[AnalysisConfig] = None,
) -> Dict[str, Any]:
    """
    Analiza una película genérica (DNLAInput) usando OMDb y devuelve
    un diccionario con los campos principales que espera el reporting.

    No escribe ficheros ni habla con Plex/DLNA; eso lo hará la capa
    que llame a esta función.
    """
    if cfg is None:
        cfg = AnalysisConfig()

    # ------------------------------------------------------------------
    # 1) Consultar OMDb (capa externa, probablemente con caché)
    # ------------------------------------------------------------------
    omdb_data: Mapping[str, Any] = {}
    try:
        omdb_data = fetch_omdb(movie.title, movie.year)
    except Exception as exc:  # pragma: no cover (defensivo)
        # Para el core nos limitamos a registrar el fallo en el resultado;
        # quien llame puede loggear más detalles si lo desea.
        omdb_data = {"Response": "False", "Error": str(exc)}

    imdb_rating, imdb_votes, rt_score = extract_omdb_fields(omdb_data)

    # ------------------------------------------------------------------
    # 2) Decisión KEEP / MAYBE / DELETE / UNKNOWN
    # ------------------------------------------------------------------
    decision, reason = decide_movie(
        imdb_rating=imdb_rating,
        imdb_votes=imdb_votes,
        rt_score=rt_score,
        cfg=cfg,
    )

    # ------------------------------------------------------------------
    # 3) Construir fila estilo report_all.csv
    # ------------------------------------------------------------------
    # Campos típicos descritos en el README:
    # - library
    # - title
    # - year
    # - imdb_rating
    # - rt_score
    # - imdb_votes
    # - plex_rating
    # - decision
    # - reason
    # - misidentified_hint
    # - file
    #
    # Añadimos además:
    # - source
    # - file_size_bytes
    #
    # Si en tu pipeline actual no existen, se pueden ignorar o mapear.
    row: Dict[str, Any] = {
        "source": movie.source,
        "library": movie.library,
        "title": movie.title,
        "year": movie.year,
        "imdb_rating": imdb_rating,
        "rt_score": rt_score,
        "imdb_votes": imdb_votes,
        "plex_rating": None,  # DLNA/local no tienen rating Plex
        "decision": decision,
        "reason": reason,
        "misidentified_hint": "",
        "file": movie.file_path,
        "file_size_bytes": movie.file_size_bytes,
    }

    # Podemos incluir info de pista IMDb si se quiere arrastrar:
    if movie.imdb_id_hint:
        row["imdb_id_hint"] = movie.imdb_id_hint

    return row