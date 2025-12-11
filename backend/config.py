import os

from dotenv import load_dotenv

# Carga de variables de entorno desde .env
load_dotenv()

PLEX_BASEURL = os.getenv("PLEX_BASEURL")
PLEX_TOKEN = os.getenv("PLEX_TOKEN")
OMDB_API_KEY = os.getenv("OMDB_API_KEY")

OUTPUT_PREFIX = os.getenv("OUTPUT_PREFIX", "report")

raw_exclude = os.getenv("EXCLUDE_LIBRARIES", "")
EXCLUDE_LIBRARIES = [x.strip() for x in raw_exclude.split(",") if x.strip()]

# ----------------------------------------------------
# Umbrales de decisión para KEEP/DELETE
# ----------------------------------------------------

# ---- KEEP thresholds ----
IMDB_KEEP_MIN_VOTES = int(os.getenv("IMDB_KEEP_MIN_VOTES", "50000"))
IMDB_KEEP_MIN_RATING = float(os.getenv("IMDB_KEEP_MIN_RATING", "7.0"))
IMDB_KEEP_MIN_RATING_WITH_RT = float(
    os.getenv("IMDB_KEEP_MIN_RATING_WITH_RT", "6.5")
)
RT_KEEP_MIN_SCORE = int(os.getenv("RT_KEEP_MIN_SCORE", "75"))

# ---- DELETE thresholds ----
RT_DELETE_MAX_SCORE = int(os.getenv("RT_DELETE_MAX_SCORE", "50"))
IMDB_DELETE_MAX_VOTES = int(os.getenv("IMDB_DELETE_MAX_VOTES", "5000"))
IMDB_DELETE_MAX_VOTES_NO_RT = int(
    os.getenv("IMDB_DELETE_MAX_VOTES_NO_RT", "2000")
)
IMDB_DELETE_MAX_RATING = float(os.getenv("IMDB_DELETE_MAX_RATING", "6.0"))

# ---- UNKNOWN thresholds ----
IMDB_MIN_VOTES_FOR_KNOWN = int(os.getenv("IMDB_MIN_VOTES_FOR_KNOWN", "1000"))

# ---- LOW thresholds (para misidentificación) ----
IMDB_RATING_LOW_THRESHOLD = float(
    os.getenv("IMDB_RATING_LOW_THRESHOLD", "3.0")
)
RT_RATING_LOW_THRESHOLD = int(
    os.getenv("RT_RATING_LOW_THRESHOLD", "20")
)

# ----------------------------------------------------
# Votos mínimos según antigüedad (para scoring justo)
#   Ejemplo en .env:
#   IMDB_VOTES_BY_YEAR="1980:500,2000:2000,2010:5000,9999:10000"
# ----------------------------------------------------
_IMDB_VOTES_BY_YEAR_RAW = os.getenv(
    "IMDB_VOTES_BY_YEAR",
    "1980:500,2000:2000,2010:5000,9999:10000",
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
      - Si la tabla está vacía: devolvemos IMDB_KEEP_MIN_VOTES (fallback clásico).
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
# Parámetros para robustecer el delete scoring
# mediante un cálculo bayesiano
# ----------------------------------------------------
ENABLE_BAYESIAN_SCORING = (
    os.getenv("ENABLE_BAYESIAN_SCORING", "false").lower() == "true"
)
BAYES_GLOBAL_MEAN_DEFAULT = float(
    os.getenv("BAYES_GLOBAL_MEAN_DEFAULT", "6.8")
)
BAYES_DELETE_MAX_SCORE = float(
    os.getenv("BAYES_DELETE_MAX_SCORE", "5.8")
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

# Modo silencioso: barra de progreso en vez de logs verbosos
SILENT_MODE = os.getenv("SILENT_MODE", "false").lower() == "true"

# ----------------------------------------------------
# Logs de depuración equivalentes a los actuales
# ----------------------------------------------------
print("DEBUG PLEX_BASEURL:", PLEX_BASEURL)
print("DEBUG TOKEN:", "****" if PLEX_TOKEN else None)
print("DEBUG EXCLUDE_LIBRARIES:", EXCLUDE_LIBRARIES)
print("DEBUG METADATA_DRY_RUN:", METADATA_DRY_RUN)
print("DEBUG METADATA_APPLY_CHANGES:", METADATA_APPLY_CHANGES)
print("DEBUG OMDB_RETRY_EMPTY_CACHE:", OMDB_RETRY_EMPTY_CACHE)
print("DEBUG SILENT_MODE:", SILENT_MODE)
print("DEBUG IMDB_VOTES_BY_YEAR:", IMDB_VOTES_BY_YEAR)