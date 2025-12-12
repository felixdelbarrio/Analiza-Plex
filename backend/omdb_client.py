# backend/omdb_client.py
import os
import json
import time
import tempfile
from pathlib import Path
from typing import Optional, Dict, Any, Tuple

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from backend.config import (
    OMDB_API_KEY,
    OMDB_RATE_LIMIT_WAIT_SECONDS,
    OMDB_RATE_LIMIT_MAX_RETRIES,
    OMDB_RETRY_EMPTY_CACHE,
    SILENT_MODE,
)
from backend import logger as _logger

# ============================================================
#                  LOGGING CONTROLADO POR SILENT_MODE
# ============================================================


def _log(msg: str) -> None:
    """Logea vía logger central respetando SILENT_MODE."""
    try:
        _logger.info(str(msg))
    except Exception:
        if not SILENT_MODE:
            print(msg)


def _log_always(msg: str) -> None:
    """Log crítico que siempre se muestra (usa logger.warning with always)."""
    try:
        _logger.warning(str(msg), always=True)
    except Exception:
        print(msg)


# HTTP session con reintentos
_SESSION: Optional[requests.Session] = None


def _get_session() -> requests.Session:
    global _SESSION
    if _SESSION is not None:
        return _SESSION
    session = requests.Session()
    retries = Retry(
        total=3,
        backoff_factor=0.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET", "POST"),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retries)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    _SESSION = session
    return _SESSION


# ============================================================
#                 FUNCIONES AUXILIARES VARIAS
# ============================================================


def _safe_int(s: Any) -> Optional[int]:
    if s is None:
        return None
    try:
        return int(s)
    except (ValueError, TypeError):
        return None


def _safe_float(s: Any) -> Optional[float]:
    if s is None:
        return None
    try:
        return float(s)
    except (ValueError, TypeError):
        return None


def normalize_imdb_votes(votes: Any) -> Optional[int]:
    """
    Convierte el campo votes de OMDb (por ejemplo "123,456") en int.
    Devuelve None si no se puede parsear.
    """
    if not votes or votes == "N/A":
        return None
    if isinstance(votes, (int, float)):
        return int(votes)

    s = str(votes).strip().replace(",", "")
    return _safe_int(s)


def parse_rt_score_from_omdb(omdb_data: Dict[str, Any]) -> Optional[int]:
    """
    Busca el rating de Rotten Tomatoes en Ratings y lo devuelve 0-100.
    """
    ratings = omdb_data.get("Ratings") or []
    for r in ratings:
        if r.get("Source") == "Rotten Tomatoes":
            val = r.get("Value")
            if not val:
                continue
            if isinstance(val, str) and val.endswith("%"):
                try:
                    return int(val[:-1])
                except ValueError:
                    return None
    return None


def parse_imdb_rating_from_omdb(omdb_data: Dict[str, Any]) -> Optional[float]:
    raw = omdb_data.get("imdbRating")
    if not raw or raw == "N/A":
        return None
    return _safe_float(raw)


def extract_year_from_omdb(omdb_data: Dict[str, Any]) -> Optional[int]:
    raw = omdb_data.get("Year")
    if not raw or raw == "N/A":
        return None
    text = str(raw).strip()
    if len(text) >= 4 and text[:4].isdigit():
        return int(text[:4])
    return None


# ============================================================
#                      CACHE OMDb LOCAL
# ============================================================

CACHE_FILE = "omdb_cache.json"
CACHE_PATH = Path(CACHE_FILE)


def load_cache() -> Dict[str, Any]:
    """
    Carga la caché de OMDb desde disco y mantiene compatibilidad
    con el formato antiguo.
    """
    if not CACHE_PATH.exists():
        return {}

    try:
        with CACHE_PATH.open("r", encoding="utf-8") as f:
            raw_cache = json.load(f)
    except Exception as e:
        _log(f"WARNING: error cargando {CACHE_PATH}: {e}")
        # Intentar renombrar el archivo corrupto para preservar datos
        try:
            broken = CACHE_PATH.with_suffix(".broken.json")
            CACHE_PATH.replace(broken)
            _log(f"INFO: archivo de cache corrupto renombrado a {broken}")
        except Exception:
            pass
        return {}

    if not isinstance(raw_cache, dict):
        return {}

    normalized: Dict[str, Any] = dict(raw_cache)

    for key, value in list(raw_cache.items()):
        if not isinstance(key, str):
            continue

        stripped = key.strip()

        # Si la clave parece un JSON antiguo → convertir
        if stripped.startswith("{") and stripped.endswith("}"):
            try:
                params = json.loads(stripped)
            except Exception:
                continue

            if not isinstance(params, dict):
                continue

            imdb_id = params.get("i")
            title = params.get("t")
            year = params.get("y")

            if imdb_id:
                canon_key = imdb_id
            elif title:
                title_low = str(title).lower()
                if year:
                    canon_key = f"title:{year}:{title_low}"
                else:
                    canon_key = f"title::{title_low}"
            else:
                canon_key = None

            if canon_key and canon_key not in normalized:
                normalized[canon_key] = value

    return normalized


def save_cache(cache: Dict[str, Any]) -> None:
    """Escribe la cache de forma atómica en CACHE_PATH."""
    dirpath = CACHE_PATH.parent
    dirpath.mkdir(parents=True, exist_ok=True)
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, dir=str(dirpath)) as tf:
            json.dump(cache, tf, indent=2, ensure_ascii=False)
            temp_name = tf.name
        os.replace(temp_name, str(CACHE_PATH))
    except Exception as e:
        _log(f"ERROR guardando cache OMDb en {CACHE_PATH}: {e}")


omdb_cache = load_cache()

# Flags globales
OMDB_DISABLED = False
OMDB_DISABLED_NOTICE_SHOWN = False
OMDB_RATE_LIMIT_NOTICE_SHOWN = False  # para el aviso de límite gratuito


# ============================================================
#                  EXTRACCIÓN DE RATINGS
# ============================================================


def extract_ratings_from_omdb(
    data: Optional[Dict[str, Any]]
) -> Tuple[Optional[float], Optional[int], Optional[int]]:
    """
    Extrae imdb_rating, imdb_votes y rt_score de un dict OMDb.
    """
    if not data:
        return None, None, None

    imdb_rating = parse_imdb_rating_from_omdb(data)
    imdb_votes = normalize_imdb_votes(data.get("imdbVotes"))
    rt_score = parse_rt_score_from_omdb(data)

    return imdb_rating, imdb_votes, rt_score


def is_omdb_data_empty_for_ratings(data: Optional[Dict[str, Any]]) -> bool:
    """
    Devuelve True si el dict OMDb no tiene rating IMDb, ni votos,
    ni puntuación de Rotten Tomatoes. Se usa para saber si una
    entrada de caché está "vacía" a efectos de scoring.
    """
    if not data:
        return True

    imdb_rating = parse_imdb_rating_from_omdb(data)
    imdb_votes = normalize_imdb_votes(data.get("imdbVotes"))
    rt_score = parse_rt_score_from_omdb(data)

    return imdb_rating is None and imdb_votes is None and rt_score is None


# ============================================================
#                      PETICIONES OMDb
# ============================================================


def omdb_request(params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Petición directa sin cache.
    """
    if OMDB_API_KEY is None:
        _log("ERROR: OMDB_API_KEY no configurada.")
        return None

    if OMDB_DISABLED:
        return None

    base_url = "https://www.omdbapi.com/"
    params = dict(params)
    params["apikey"] = OMDB_API_KEY

    try:
        session = _get_session()
        resp = session.get(base_url, params=params, timeout=10)
    except Exception as e:
        _log(f"WARNING: error al conectar con OMDb: {e}")
        return None

    # Comprobar código HTTP
    if resp.status_code != 200:
        _log(f"WARNING: OMDb devolvió status {resp.status_code}")
        return None

    try:
        data_obj = resp.json()
    except Exception as e:
        _log(f"WARNING: OMDb no devolvió JSON válido: {e}")
        return None

    if isinstance(data_obj, dict):
        return data_obj
    _log("WARNING: OMDb devolvió JSON no dict.")
    return None


def omdb_query_with_cache(cache_key: str, params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Gestiona:
    - Cache OMDb.
    - OMDB_RETRY_EMPTY_CACHE.
    - Reintentos por rate limit.
    - Desactivación global de OMDb.

    Además:
    - Cuando OMDb responde "Request limit reached!", mostramos SIEMPRE
      un aviso (una sola vez) y esperamos OMDB_RATE_LIMIT_WAIT_SECONDS
      antes de seguir.
    """
    global OMDB_DISABLED, OMDB_DISABLED_NOTICE_SHOWN, OMDB_RATE_LIMIT_NOTICE_SHOWN

    # Si OMDb está desactivado → solo cache
    if OMDB_DISABLED:
        return omdb_cache.get(cache_key)

    # Cache hit (normal, sin reintento)
    if cache_key in omdb_cache and not OMDB_RETRY_EMPTY_CACHE:
        return omdb_cache[cache_key]

    # Cache hit pero se quiere volver a intentar porque estaba "vacía" de ratings
    if cache_key in omdb_cache and OMDB_RETRY_EMPTY_CACHE:
        old = omdb_cache[cache_key]
        if not is_omdb_data_empty_for_ratings(old):
            # ya tiene algún rating/votos/RT → usarla y no llamar a OMDb
            return old
        else:
            _log(f"INFO: reintentando OMDb para {cache_key} (cache sin ratings).")

    # Reintentos reales a la API
    retries = 0
    had_failure = False

    while retries <= OMDB_RATE_LIMIT_MAX_RETRIES:
        data = omdb_request(params)

        if data is None:
            had_failure = True

        else:
            error_msg = data.get("Error")

            # ----------------------------
            # Caso: límite gratuito OMDb
            # ----------------------------
            if error_msg == "Request limit reached!":
                had_failure = True

                if not OMDB_RATE_LIMIT_NOTICE_SHOWN:
                    _log_always(
                        "AVISO: límite de llamadas gratuitas de OMDb alcanzado. "
                        f"Esperando {OMDB_RATE_LIMIT_WAIT_SECONDS} segundos antes de continuar..."
                    )
                    OMDB_RATE_LIMIT_NOTICE_SHOWN = True

                    # Espera ÚNICA configurable desde el .env
                    time.sleep(OMDB_RATE_LIMIT_WAIT_SECONDS)

                # seguimos el bucle SIN más sleeps genéricos
                retries += 1
                continue

            # ----------------------------
            # Caso normal con datos (OK o 'Movie not found')
            # ----------------------------
            if data.get("Response") == "True":
                omdb_cache[cache_key] = data
                save_cache(omdb_cache)
                return data

            # Error no fatal (por ejemplo Movie not found) → almacenar y devolver
            omdb_cache[cache_key] = data
            save_cache(omdb_cache)
            return data

        retries += 1

    # ------------------------------------------------------------------
    # Si agotamos todos los reintentos → desactivamos OMDb para la sesión
    # ------------------------------------------------------------------
    if had_failure:
        OMDB_DISABLED = True
        if not OMDB_DISABLED_NOTICE_SHOWN:
            _log_always(
                "ERROR: OMDb desactivado para esta ejecución tras fallos consecutivos. "
                "A partir de ahora se usará únicamente la caché local."
            )
            OMDB_DISABLED_NOTICE_SHOWN = True

    return omdb_cache.get(cache_key)


# ============================================================
#                      FUNCIONES PÚBLICAS
# ============================================================


def search_omdb_by_imdb_id(imdb_id: str) -> Optional[Dict[str, Any]]:
    if not imdb_id:
        return None

    cache_key = imdb_id
    params = {"i": imdb_id, "type": "movie", "plot": "short"}
    return omdb_query_with_cache(cache_key, params)


def search_omdb_by_title_and_year(
    title: str, year: Optional[int]
) -> Optional[Dict[str, Any]]:
    if not title:
        return None

    cache_key = f"title:{year}:{title.lower()}" if year else f"title::{title.lower()}"
    params = {"t": title, "type": "movie", "plot": "short"}

    if year:
        params["y"] = str(year)

    data = omdb_query_with_cache(cache_key, params)

    # Reintento sin año si OMDb dice "Movie not found!"
    if data and data.get("Response") == "False" and data.get("Error") == "Movie not found!":
        cache_key_no_year = f"title::{title.lower()}"
        params_no_year = dict(params)
        params_no_year.pop("y", None)
        data = omdb_query_with_cache(cache_key_no_year, params_no_year)

    return data


def search_omdb_with_candidates(
    plex_title: str, plex_year: Optional[int]
) -> Optional[Dict[str, Any]]:
    """
    Último recurso cuando:
      - No se obtuvo IMDb ID
      - No se encuentra título exacto

    Estrategia:
      1) Buscar por título+year.
      2) Si falla, usar 's=' de OMDb y elegir el mejor candidato por heurística.
    """
    title = plex_title.strip() if plex_title else ""
    if not title:
        return None

    # 1) búsqueda directa título+year
    data = search_omdb_by_title_and_year(title, plex_year)
    if data and data.get("Response") == "True":
        return data

    # 2) búsqueda por 's' de OMDb (búsqueda libre)
    base_url = "https://www.omdbapi.com/"
    params = {"apikey": OMDB_API_KEY, "s": title, "type": "movie"}

    try:
        session = _get_session()
        resp = session.get(base_url, params=params, timeout=10)
        data_s = resp.json() if resp.status_code == 200 else None
    except Exception:
        data_s = None

    if not data_s or data_s.get("Response") != "True":
        return None

    results = data_s.get("Search") or []
    if not isinstance(results, list):
        return None

    # scoring básico de candidatos
    def score_candidate(cand: Dict[str, Any]) -> float:
        score = 0.0

        ctit = (cand.get("Title") or "").lower()
        ptit = title.lower()

        if ptit == ctit:
            score += 2.0
        elif ctit in ptit or ptit in ctit:
            score += 1.0

        cand_year = None
        cy = cand.get("Year")
        if cy and cy != "N/A":
            try:
                cand_year = int(cy[:4])
            except Exception:
                pass

        if plex_year and cand_year:
            if plex_year == cand_year:
                score += 2.0
            elif abs(plex_year - cand_year) <= 1:
                score += 1.0

        # coincidencia parcial por palabras
        common = sum(1 for w in ptit.split() if w and w in ctit)
        score += common * 0.1

        return score

    # elegir el mejor candidato
    best = max(results, key=lambda c: score_candidate(c), default=None)
    if not best:
        return None

    imdb_id = best.get("imdbID")
    if not imdb_id:
        return None

    return search_omdb_by_imdb_id(imdb_id)