import os
import json
import time
from typing import Optional, Dict, Any, Tuple

import requests

from backend.config import (
    OMDB_API_KEY,
    OMDB_RATE_LIMIT_WAIT_SECONDS,
    OMDB_RATE_LIMIT_MAX_RETRIES,
    OMDB_RETRY_EMPTY_CACHE,
)

# ============================================================
#  googletrans opcional para traducir títulos ES->EN
# ============================================================

try:
    from googletrans import Translator  # pip install googletrans==4.0.0-rc1

    _TRANSLATOR = Translator()
    print(
        "INFO: googletrans disponible, se podrá traducir títulos ES->EN si es necesario."
    )
except Exception:
    _TRANSLATOR = None
    print("INFO: googletrans NO disponible, se usarán títulos tal cual para OMDb.")


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


def translate_title_es_to_en(title: str) -> str:
    if not title:
        return title
    if _TRANSLATOR is None:
        return title
    try:
        t = _TRANSLATOR.translate(title, src="es", dest="en")
        if t and t.text:
            return t.text
        return title
    except Exception as e:
        print(f"WARNING: error traduciendo título '{title}': {e}")
        return title


# ============================================================
#                      CACHE OMDb LOCAL
# ============================================================

CACHE_FILE = "omdb_cache.json"


def load_cache() -> Dict[str, Any]:
    """
    Carga la caché de OMDb desde disco y mantiene compatibilidad con el formato antiguo.

    Formato antiguo de claves (antes del refactor):
      '{"i": "tt0103639", "type": "movie"}'
      '{"t": "Aladdin", "type": "movie", "y": "1992"}'

    Formato nuevo de claves:
      'tt0103639'
      'title:1992:aladdin'
      'title::aladdin'
    """
    if not os.path.exists(CACHE_FILE):
        return {}

    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            raw_cache = json.load(f)
    except Exception:
        return {}

    if not isinstance(raw_cache, dict):
        return {}

    # Partimos del contenido tal cual
    normalized: Dict[str, Any] = dict(raw_cache)

    for key, value in list(raw_cache.items()):
        if not isinstance(key, str):
            continue

        stripped = key.strip()
        # Solo intentamos parsear como JSON si parece un dict serializado
        if not (stripped.startswith("{") and stripped.endswith("}")):
            continue

        try:
            params = json.loads(stripped)
        except Exception:
            continue

        if not isinstance(params, dict):
            continue

        imdb_id = params.get("i")
        title = params.get("t")
        year = params.get("y")

        canon_key = None
        if imdb_id:
            canon_key = imdb_id
        elif title:
            title_low = str(title).lower()
            if year:
                canon_key = f"title:{year}:{title_low}"
            else:
                canon_key = f"title::{title_low}"

        if canon_key and canon_key not in normalized:
            normalized[canon_key] = value

    return normalized


def save_cache(cache: Dict[str, Any]) -> None:
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2, ensure_ascii=False)


omdb_cache = load_cache()

# Flags globales para controlar OMDb
OMDB_DISABLED = False
OMDB_DISABLED_NOTICE_SHOWN = False  # para no spamear el mensaje


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


def extract_ratings_from_omdb_detail(
    data: Optional[Dict[str, Any]]
) -> Tuple[Optional[float], Optional[int], Optional[int]]:
    """
    Alias que mantenemos por compatibilidad con el backend actual.
    """
    return extract_ratings_from_omdb(data)


def is_omdb_data_empty_for_ratings(data: Optional[Dict[str, Any]]) -> bool:
    """
    Devuelve True si el dict OMDb no tiene ratings ni votos ni RT.
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
    Realiza una petición directa a OMDb (sin cache) con parámetros dados.
    Devuelve:
      - dict con el JSON devuelto por OMDb (aunque sea Error/Response=False)
      - None en caso de error de red / respuesta no JSON
    NO modifica OMDB_DISABLED; la política se decide en omdb_query_with_cache.
    """
    if OMDB_API_KEY is None:
        print("ERROR: OMDB_API_KEY no configurada, no se puede usar OMDb.")
        return None

    if OMDB_DISABLED:
        return None

    base_url = "https://www.omdbapi.com/"
    params = dict(params)
    params["apikey"] = OMDB_API_KEY

    try:
        resp = requests.get(base_url, params=params, timeout=10)
    except Exception as e:
        print(f"WARNING: error al hacer request a OMDb: {e}")
        return None

    try:
        data_obj = resp.json()
        if isinstance(data_obj, dict):
            return data_obj
        print("WARNING: OMDb devolvió un JSON no dict.")
        return None
    except Exception as e:
        print(f"WARNING: respuesta OMDb no es JSON válido: {e}")
        return None


def omdb_query_with_cache(cache_key: str, params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Envuelve omdb_request con caché, reintentos y política de desactivación.
    Reglas:
      - Respeta OMDB_RETRY_EMPTY_CACHE.
      - Reintenta hasta OMDB_RATE_LIMIT_MAX_RETRIES, esperando
        OMDB_RATE_LIMIT_WAIT_SECONDS entre intentos.
      - Después de agotar reintentos, desactiva OMDb para toda la ejecución
        (OMDB_DISABLED=True) y no vuelve a hacer peticiones.
      - Una vez desactivado, SOLO usa la caché y NO muestra más mensajes.
    """
    global OMDB_DISABLED, OMDB_DISABLED_NOTICE_SHOWN

    # Si OMDb ya está desactivado: no hacemos peticiones nuevas
    if OMDB_DISABLED:
        if cache_key in omdb_cache:
            return omdb_cache[cache_key]
        # silencioso: no mostramos nada más
        return None

    # Caché normal
    if cache_key in omdb_cache and not OMDB_RETRY_EMPTY_CACHE:
        return omdb_cache[cache_key]

    # Caché con reintentos para entradas "vacías"
    if cache_key in omdb_cache and OMDB_RETRY_EMPTY_CACHE:
        old_data = omdb_cache[cache_key]
        if not is_omdb_data_empty_for_ratings(old_data):
            return old_data
        else:
            print(
                f"INFO: reintentando OMDb para clave {cache_key} porque la caché no tiene ratings."
            )

    retries = 0
    had_failure = False

    while retries <= OMDB_RATE_LIMIT_MAX_RETRIES:
        data = omdb_request(params)

        # Error "duro": sin datos (network, timeout, etc.)
        if data is None:
            had_failure = True
        else:
            # Miramos errores de OMDb en el JSON
            error_msg = data.get("Error")
            if error_msg == "Request limit reached!":
                # Esto también cuenta como fallo, pero respetando reintentos
                had_failure = True
            else:
                # Tenemos una respuesta "normal" (Response True o False)
                if data.get("Response") == "True":
                    # Éxito -> guardamos en caché y devolvemos
                    omdb_cache[cache_key] = data
                    save_cache(omdb_cache)
                    return data
                else:
                    # Error "normal" (por ejemplo Movie not found) -> cache y devolvemos
                    omdb_cache[cache_key] = data
                    save_cache(omdb_cache)
                    return data

        # Si llegamos aquí, no tenemos respuesta utilizable todavía
        retries += 1
        if retries <= OMDB_RATE_LIMIT_MAX_RETRIES:
            # Mensaje de reintento mientras aún hay intentos
            print(
                f"INFO: fallo consultando OMDb (intento {retries}/{OMDB_RATE_LIMIT_MAX_RETRIES}); "
                f"reintentando en {OMDB_RATE_LIMIT_WAIT_SECONDS} segundos..."
            )
            time.sleep(OMDB_RATE_LIMIT_WAIT_SECONDS)

    # Hemos agotado los reintentos
    if had_failure:
        OMDB_DISABLED = True
        if not OMDB_DISABLED_NOTICE_SHOWN:
            print(
                "ERROR: OMDb desactivado para esta ejecución tras agotar "
                f"{OMDB_RATE_LIMIT_MAX_RETRIES} reintentos."
            )
            OMDB_DISABLED_NOTICE_SHOWN = True

    # Devolvemos lo que haya en caché (si algo se hubiera guardado antes)
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
    Búsqueda "inteligente" usando título Plex, año y candidatos de OMDb.
    Puede usar traducción ES->EN si googletrans está disponible.
    """
    title = plex_title or ""
    title = title.strip()
    if not title:
        return None

    data = search_omdb_by_title_and_year(title, plex_year)
    if data and data.get("Response") == "True":
        return data

    if _TRANSLATOR is not None:
        translated_title = translate_title_es_to_en(title)
        if translated_title.lower() != title.lower():
            print(
                "INFO: intentando búsqueda OMDb con título traducido "
                f"'{translated_title}' (desde '{title}')."
            )
            data = search_omdb_by_title_and_year(translated_title, plex_year)
            if data and data.get("Response") == "True":
                return data

    base_url = "https://www.omdbapi.com/"
    params = {"apikey": OMDB_API_KEY, "s": title, "type": "movie"}
    try:
        resp = requests.get(base_url, params=params, timeout=10)
        if resp.status_code != 200:
            return None
        data_s = resp.json()
    except Exception:
        data_s = None

    if not data_s or data_s.get("Response") != "True":
        return None

    results = data_s.get("Search") or []
    results = results if isinstance(results, list) else []

    def score_candidate(
        plex_title: str, plex_year: Optional[int], cand: Dict[str, Any]
    ) -> float:
        cand_year = None
        try:
            cy = cand.get("Year")
            if cy and cy != "N/A":
                cand_year = int(cy[:4])
        except Exception:
            pass

        score = 0.0

        if plex_year and cand_year:
            if plex_year == cand_year:
                score += 2.0
            elif abs(plex_year - cand_year) <= 1:
                score += 1.0

        ctit = (cand.get("Title") or "").lower()
        ptit = (plex_title or "").lower()

        if ctit == ptit:
            score += 2.0
        elif ctit in ptit or ptit in ctit:
            score += 1.0

        common = 0
        for word in ptit.split():
            if word and word in ctit:
                common += 1
        score += 0.1 * common

        return score

    best_cand = None
    best_score = -1.0

    for cand in results:
        s = score_candidate(title, plex_year, cand)
        if s > best_score:
            best_score = s
            best_cand = cand

    if not best_cand:
        return None

    imdb_id = best_cand.get("imdbID")
    if not imdb_id:
        return None

    return search_omdb_by_imdb_id(imdb_id)