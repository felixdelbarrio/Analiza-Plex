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

# Umbrales de decisión para KEEP/DELETE
#---- keep thresholds ----
IMDB_KEEP_MIN_VOTES = int(os.getenv("IMDB_KEEP_MIN_VOTES", "50000"))
IMDB_KEEP_MIN_RATING = float(os.getenv("IMDB_KEEP_MIN_RATING", "7.0"))
IMDB_KEEP_MIN_RATING_WITH_RT = float(
    os.getenv("IMDB_KEEP_MIN_RATING_WITH_RT", "6.5")
)
RT_KEEP_MIN_SCORE = int(os.getenv("RT_KEEP_MIN_SCORE", "75"))
#---- delete thresholds ----
RT_DELETE_MAX_SCORE = int(os.getenv("RT_DELETE_MAX_SCORE", "50"))
IMDB_DELETE_MAX_VOTES = int(os.getenv("IMDB_DELETE_MAX_VOTES", "5000"))
IMDB_DELETE_MAX_VOTES_NO_RT = int(
    os.getenv("IMDB_DELETE_MAX_VOTES_NO_RT", "2000")
)
IMDB_DELETE_MAX_RATING = float(os.getenv("IMDB_DELETE_MAX_RATING", "6.0"))
#---- unkown thresholds ----
IMDB_MIN_VOTES_FOR_KNOWN = int(os.getenv("IMDB_MIN_VOTES_FOR_KNOWN", "1000"))
# LOW thresholds"
IMDB_RATING_LOW_THRESHOLD= float(os.getenv("IMDB_RATING_LOW_THRESHOLD", "3.0"))
RT_RATING_LOW_THRESHOLD= int(os.getenv("RT_RATING_LOW_THRESHOLD", "20"))


# Rate limit OMDb
OMDB_RATE_LIMIT_WAIT_SECONDS = int(
    os.getenv("OMDB_RATE_LIMIT_WAIT_SECONDS", "60")
)
OMDB_RATE_LIMIT_MAX_RETRIES = int(
    os.getenv("OMDB_RATE_LIMIT_MAX_RETRIES", "1")
)

# Parámetros extra para corrección de metadata
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

# Logs de depuración equivalentes a los actuales
print("DEBUG PLEX_BASEURL:", PLEX_BASEURL)
print("DEBUG TOKEN:", "****" if PLEX_TOKEN else None)
print("DEBUG EXCLUDE_LIBRARIES:", EXCLUDE_LIBRARIES)
print("DEBUG METADATA_DRY_RUN:", METADATA_DRY_RUN)
print("DEBUG METADATA_APPLY_CHANGES:", METADATA_APPLY_CHANGES)
print("DEBUG OMDB_RETRY_EMPTY_CACHE:", OMDB_RETRY_EMPTY_CACHE)
print("DEBUG SILENT_MODE:", SILENT_MODE)