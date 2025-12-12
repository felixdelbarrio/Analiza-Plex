# backend/config.py
import os
from typing import Any

from dotenv import load_dotenv

# Carga de variables de entorno desde .env
load_dotenv()

# ----------------------------------------------------
# Conexión a Plex / OMDb
# ----------------------------------------------------
PLEX_BASEURL = os.getenv("PLEX_BASEURL")
PLEX_TOKEN = os.getenv("PLEX_TOKEN")
OMDB_API_KEY = os.getenv("OMDB_API_KEY")

# Prefijo de ficheros de salida (report_all, report_filtered, etc.)
OUTPUT_PREFIX = os.getenv("OUTPUT_PREFIX", "report")

raw_exclude = os.getenv("EXCLUDE_LIBRARIES", "")
EXCLUDE_LIBRARIES = [x.strip() for x in raw_exclude.split(",") if x.strip()]

# ----------------------------------------------------
# Umbrales de decisión para KEEP/DELETE
# ----------------------------------------------------
#
# IMPORTANTE:
# - El scoring principal es bayesiano (BAYES_*).
# - Estos valores actúan como refuerzo adicional y/o fallback
#   cuando no hay datos suficientes en omdb_cache.
# ----------------------------------------------------

# ---- Rotten Tomatoes (positivo / negativo) ----
RT_KEEP_MIN_SCORE = int(
    os.getenv("RT_KEEP_MIN_SCORE", "55")
)  # RT >= 55% + buen IMDb → refuerza KEEP

RT_DELETE_MAX_SCORE = int(
    os.getenv("RT_DELETE_MAX_SCORE", "50")
)  # RT muy bajo → refuerza DELETE

# ---- IMDb con RT (refuerzo positivo) ----
IMDB_KEEP_MIN_RATING_WITH_RT = float(
    os.getenv("IMDB_KEEP_MIN_RATING_WITH_RT", "6.0")
)  # IMDb mínimo cuando RT es aceptable

# ---- Fallbacks de rating (cuando no hay suficientes datos para auto-umbrales) ----
IMDB_KEEP_MIN_RATING = float(
    os.getenv("IMDB_KEEP_MIN_RATING", "5.7")
)  # solo fallback si no hay suficientes títulos para percentiles

IMDB_DELETE_MAX_RATING = float(
    os.getenv("IMDB_DELETE_MAX_RATING", "5.5")
)  # solo fallback si no hay suficientes títulos para percentiles

# ---- Votos mínimos globales (fallback) ----
IMDB_KEEP_MIN_VOTES = int(
    os.getenv("IMDB_KEEP_MIN_VOTES", "30000")
)  # se usa solo si IMDB_VOTES_BY_YEAR está vacío

# ---- UNKNOWN por falta de información ----
IMDB_MIN_VOTES_FOR_KNOWN = int(
    os.getenv("IMDB_MIN_VOTES_FOR_KNOWN", "100")
)  # menos de esto → UNKNOWN

# ---- LOW thresholds (para misidentificación / sospechosos) ----
IMDB_RATING_LOW_THRESHOLD = float(
    os.getenv("IMDB_RATING_LOW_THRESHOLD", "3.0")
)
RT_RATING_LOW_THRESHOLD = int(
    os.getenv("RT_RATING_LOW_THRESHOLD", "20")
)

# ----------------------------------------------------
# Auto-umbrales de rating desde omdb_cache
#   (se usan en backend.stats para calcular umbrales
#    KEEP/DELETE dinámicos por percentil; si no hay
#    suficientes títulos válidos, se cae en los
#    fallbacks IMDB_KEEP_MIN_RATING / IMDB_DELETE_MAX_RATING)
# ----------------------------------------------------
AUTO_KEEP_RATING_PERCENTILE = float(
    os.getenv("AUTO_KEEP_RATING_PERCENTILE", "0.70")  # top 30% = buenas
)
AUTO_DELETE_RATING_PERCENTILE = float(
    os.getenv("AUTO_DELETE_RATING_PERCENTILE", "0.01")  # peor 1% = muy malas
)
RATING_MIN_TITLES_FOR_AUTO = int(
    os.getenv("RATING_MIN_TITLES_FOR_AUTO", "300")  # mínimo para aplicar percentiles
)

# ----------------------------------------------------
# Votos mínimos según antigüedad (para m en Bayes)
#   Ejemplo en .env:
#   IMDB_VOTES_BY_YEAR="1980:500,2000:2000,2010:5000,9999:10000"
# ----------------------------------------------------
_IMDB_VOTES_BY_YEAR_RAW = os.getenv(
    "IMDB_VOTES_BY_YEAR",
    "1980:500,2000:2000,2010:5000,9999:10000",
)

# ---- Metacritic (crítica especializada, 0-100) ----
METACRITIC_KEEP_MIN_SCORE = int(
    os.getenv("METACRITIC_KEEP_MIN_SCORE", "70")  # buena crítica refuerza KEEP
)
METACRITIC_DELETE_MAX_SCORE = int(
    os.getenv("METACRITIC_DELETE_MAX_SCORE", "40")  # crítica muy mala refuerza DELETE
)


def _parse_votes_by_year(raw: str):
    """
    Parsea cadenas tipo:
      1980:500,2000:2000,2010:5000,9999:10000

    Admitiendo también comillas alrededor:
      "1980:500,2000:2000,2010:5000,9999:10000"
      '1980:500,2000:2000,2010:5000,9999:10000'
    """
    if not raw:
        return []

    # Quitamos comillas exteriores si las hay y espacios
    cleaned = raw.strip().strip('"').strip("'")

    table = []
    for part in cleaned.split(","):
        chunk = part.strip()
        if not chunk:
            continue
        try:
            year_limit_str, votes_min_str = chunk.split(":")
            year_limit = int(year_limit_str.strip())
            votes_min = int(votes_min_str.strip())
            table.append((year_limit, votes_min))
        except Exception:
            # Si hay algún trozo mal formado lo ignoramos silenciosamente
            continue

    # Ordenamos por año límite ascendente para que sea determinista
    return sorted(table, key=lambda x: x[0])


IMDB_VOTES_BY_YEAR = _parse_votes_by_year(_IMDB_VOTES_BY_YEAR_RAW)


def get_votes_threshold_for_year(year: int | None) -> int:
    """
    Devuelve el número mínimo de votos exigidos para una película
    según su año, usando la tabla IMDB_VOTES_BY_YEAR.

    Reglas:
      - Si la tabla está vacía: devolvemos IMDB_KEEP_MIN_VOTES (fallback).
      - Si year es None o no es convertible a int: usamos el tramo más exigente
        (último de IMDB_VOTES_BY_YEAR).
      - Recorre IMDB_VOTES_BY_YEAR y devuelve el primer votes_min
        cuyo year_limit sea >= year.
    """
    # Si no hay tabla válida, caemos al umbral fijo clásico
    if not IMDB_VOTES_BY_YEAR:
        return IMDB_KEEP_MIN_VOTES

    try:
        y = int(year) if year is not None else None
    except (TypeError, ValueError):
        y = None

    # Si no hay año, usamos la regla más exigente (último tramo)
    if y is None:
        return IMDB_VOTES_BY_YEAR[-1][1]

    for year_limit, votes_min in IMDB_VOTES_BY_YEAR:
        if y <= year_limit:
            return votes_min

    # Si por lo que sea no ha hecho match, usamos también el último tramo
    return IMDB_VOTES_BY_YEAR[-1][1]


# ----------------------------------------------------
# Parámetros para el scoring bayesiano global
# ----------------------------------------------------
BAYES_GLOBAL_MEAN_DEFAULT = float(
    os.getenv("BAYES_GLOBAL_MEAN_DEFAULT", "6.0")
)
BAYES_DELETE_MAX_SCORE = float(
    os.getenv("BAYES_DELETE_MAX_SCORE", "4.9")
)
BAYES_MIN_TITLES_FOR_GLOBAL_MEAN = int(
    os.getenv("BAYES_MIN_TITLES_FOR_GLOBAL_MEAN", "200")
)

# ----------------------------------------------------
# Rate limit OMDb
# ----------------------------------------------------
OMDB_RATE_LIMIT_WAIT_SECONDS = int(
    os.getenv("OMDB_RATE_LIMIT_WAIT_SECONDS", "60")
)
OMDB_RATE_LIMIT_MAX_RETRIES = int(
    os.getenv("OMDB_RATE_LIMIT_MAX_RETRIES", "1")
)

# ----------------------------------------------------
# Parámetros extra para corrección de metadata
# ----------------------------------------------------
METADATA_OUTPUT_PREFIX = os.getenv("METADATA_OUTPUT_PREFIX", "metadata_fix")
METADATA_MIN_RATING_FOR_OK = float(
    os.getenv("METADATA_MIN_RATING_FOR_OK", "6.0")
)
METADATA_MIN_VOTES_FOR_OK = int(
    os.getenv("METADATA_MIN_VOTES_FOR_OK", "2000")
)

METADATA_DRY_RUN = os.getenv("METADATA_DRY_RUN", "true").lower() == "true"
METADATA_APPLY_CHANGES = (
    os.getenv("METADATA_APPLY_CHANGES", "false").lower() == "true"
)

# Reintentar entradas de caché sin rating/votos
OMDB_RETRY_EMPTY_CACHE = (
    os.getenv("OMDB_RETRY_EMPTY_CACHE", "false").lower() == "true"
)

# Modo silencioso (afecta a logs en varios módulos)
SILENT_MODE = os.getenv("SILENT_MODE", "false").lower() == "true"

# ----------------------------------------------------
# Logs de depuración equivalentes a los actuales
# (controlados por SILENT_MODE)
# ----------------------------------------------------
def _log_config_debug(label: str, value: Any) -> None:
    """
    Imprime configuración solo si SILENT_MODE=False.
    Evita ensuciar la consola cuando se quiere ejecución silenciosa.
    """
    if not SILENT_MODE:
        print(f"{label}: {value}")


_log_config_debug("DEBUG PLEX_BASEURL", PLEX_BASEURL)
_log_config_debug("DEBUG TOKEN", "****" if PLEX_TOKEN else None)
_log_config_debug("DEBUG EXCLUDE_LIBRARIES", EXCLUDE_LIBRARIES)
_log_config_debug("DEBUG METADATA_DRY_RUN", METADATA_DRY_RUN)
_log_config_debug("DEBUG METADATA_APPLY_CHANGES", METADATA_APPLY_CHANGES)
_log_config_debug("DEBUG OMDB_RETRY_EMPTY_CACHE", OMDB_RETRY_EMPTY_CACHE)
_log_config_debug("DEBUG SILENT_MODE", SILENT_MODE)
_log_config_debug("DEBUG IMDB_VOTES_BY_YEAR", IMDB_VOTES_BY_YEAR)