# backend/wiki_client.py
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import requests
import os
import tempfile

from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from backend.config import OMDB_RETRY_EMPTY_CACHE, SILENT_MODE
from backend.omdb_client import (
    search_omdb_by_imdb_id,
    search_omdb_with_candidates,
    omdb_cache,
    is_omdb_data_empty_for_ratings,
)
from backend import logger as _logger

# --------------------------------------------------------------------
# Fichero de caché maestro (wiki + omdb fusionado)
# --------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
WIKI_CACHE_PATH = BASE_DIR / "wiki_cache.json"

_wiki_cache: Dict[str, Dict[str, Any]] = {}
_wiki_cache_loaded = False

# Contexto de progreso para prefijar logs (x/total, biblioteca, título)
_CURRENT_PROGRESS: Dict[str, Any] = {
    "idx": None,
    "total": None,
    "library": None,
    "title": None,
}


def set_wiki_progress(idx: int, total: int, library_title: str, movie_title: str) -> None:
    """
    Se llama desde analiza_plex para que los logs de wiki_client sepan
    en qué punto del análisis estamos y puedan prefijar (x/total).
    """
    _CURRENT_PROGRESS["idx"] = idx
    _CURRENT_PROGRESS["total"] = total
    _CURRENT_PROGRESS["library"] = library_title
    _CURRENT_PROGRESS["title"] = movie_title


def _progress_prefix() -> str:
    idx = _CURRENT_PROGRESS.get("idx")
    total = _CURRENT_PROGRESS.get("total")
    library = _CURRENT_PROGRESS.get("library")
    title = _CURRENT_PROGRESS.get("title")

    if idx is None or total is None or library is None or title is None:
        return ""

    return f"({idx}/{total}) {library} · {title} | "


def _log_wiki(msg: str) -> None:
    """
    Log interno de wiki_client controlado por SILENT_MODE.
    """
    prefix = _progress_prefix()
    # Use centralized logger which respects SILENT_MODE
    try:
        _logger.info(prefix + msg)
    except Exception:
        # Fallback to print if logger fails for any reason
        if not SILENT_MODE:
            print(prefix + msg)


# --------------------------------------------------------------------
# HTTP session with retries
# --------------------------------------------------------------------
_SESSION: Optional[requests.Session] = None


def _get_session() -> requests.Session:
    """Return a cached requests.Session configured with retries/backoff."""
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


# --------------------------------------------------------------------
# Carga / guardado de wiki_cache
# --------------------------------------------------------------------
def _load_wiki_cache() -> None:
    global _wiki_cache_loaded, _wiki_cache
    if _wiki_cache_loaded:
        return
    if WIKI_CACHE_PATH.exists():
        try:
            with WIKI_CACHE_PATH.open("r", encoding="utf-8") as f:
                _wiki_cache = json.load(f)
            _log_wiki(f"[WIKI] wiki_cache cargada ({len(_wiki_cache)} entradas)")
        except Exception as e:
            _logger.warning(f"[WIKI] Error cargando wiki_cache.json: {e}")
            # Try to preserve the broken file before resetting cache
            try:
                broken = WIKI_CACHE_PATH.with_suffix(".broken.json")
                WIKI_CACHE_PATH.replace(broken)
                _logger.warning(f"[WIKI] Archivo corrupto renombrado a {broken}")
            except Exception:
                # best-effort, ignore
                pass
            _wiki_cache = {}
    else:
        _wiki_cache = {}
    _wiki_cache_loaded = True


def _save_wiki_cache() -> None:
    if not _wiki_cache_loaded:
        return
    try:
        # Write atomically to avoid corrupting cache on crash
        dirpath = WIKI_CACHE_PATH.parent
        dirpath.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, dir=str(dirpath)) as tf:
            json.dump(_wiki_cache, tf, ensure_ascii=False, indent=2)
            temp_name = tf.name
        os.replace(temp_name, str(WIKI_CACHE_PATH))
    except Exception as e:
        _logger.error(f"[WIKI] Error guardando wiki_cache.json: {e}")


def _normalize_title(title: str) -> str:
    return " ".join((title or "").strip().lower().split())


# --------------------------------------------------------------------
# Consultas a Wikidata / Wikipedia
# --------------------------------------------------------------------
WIKIDATA_API = "https://www.wikidata.org/w/api.php"
WIKIDATA_SPARQL = "https://query.wikidata.org/sparql"
WIKIPEDIA_API_TEMPLATE = "https://{lang}.wikipedia.org/w/api.php"


def _wikidata_get_entity(wikidata_id: str) -> Optional[Dict[str, Any]]:
    try:
        session = _get_session()
        resp = session.get(
            WIKIDATA_API,
            params={
                "action": "wbgetentities",
                "ids": wikidata_id,
                "format": "json",
                "props": "labels|claims|sitelinks",
            },
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("entities", {}).get(wikidata_id)
    except Exception as e:
        _log_wiki(f"[WIKI] Error obteniendo entidad {wikidata_id} de Wikidata: {e}")
        return None


def _wikidata_search_by_imdb(imdb_id: str) -> Optional[Tuple[str, Dict[str, Any]]]:
    """
    Busca en Wikidata por propiedad P345 (IMDb ID).
    Devuelve (wikidata_id, entity) o None.
    """
    query = f"""
    SELECT ?item WHERE {{
      ?item wdt:P345 "{imdb_id}" .
    }} LIMIT 1
    """

    try:
        session = _get_session()
        resp = session.get(
            WIKIDATA_SPARQL,
            params={"query": query, "format": "json"},
            headers={"Accept": "application/sparql-results+json"},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        results = data.get("results", {}).get("bindings", [])
        if not results:
            return None

        item_uri = results[0]["item"]["value"]
        wikidata_id = item_uri.split("/")[-1]
        entity = _wikidata_get_entity(wikidata_id)
        if not entity:
            return None

        return wikidata_id, entity
    except Exception as e:
        _log_wiki(f"[WIKI] Error en búsqueda SPARQL por IMDb ID {imdb_id}: {e}")
        return None


def _wikidata_search_by_title(
    title: str,
    year: Optional[int],
    language: str = "en",
) -> Optional[Tuple[str, Dict[str, Any]]]:
    """
    Busca una película por título (y opcionalmente año) usando wbsearchentities.
    Filtra por tipo 'film' y comprueba fecha aproximada de publicación.
    """
    try:
        session = _get_session()
        resp = session.get(
            WIKIDATA_API,
            params={
                "action": "wbsearchentities",
                "search": title,
                "language": language,
                "type": "item",
                "format": "json",
                "limit": 5,
            },
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        search_results = data.get("search", [])
        if not search_results:
            return None

        for candidate in search_results:
            wikidata_id = candidate.get("id")
            entity = _wikidata_get_entity(wikidata_id)
            if not entity:
                continue

            claims = entity.get("claims", {})

            # P31 = instance of → film / animated film
            if "P31" in claims:
                ok_type = False
                for inst in claims["P31"]:
                    val = (
                        inst.get("mainsnak", {})
                        .get("datavalue", {})
                        .get("value", {})
                    )
                    if isinstance(val, dict) and val.get("id") in {
                        "Q11424",  # film
                        "Q24869",  # animated film
                    }:
                        ok_type = True
                        break
                if not ok_type:
                    continue

            # P577 = publication date
            if year and "P577" in claims:
                try:
                    time_str = (
                        claims["P577"][0]
                        .get("mainsnak", {})
                        .get("datavalue", {})
                        .get("value", {})
                        .get("time")
                    )
                    if time_str and len(time_str) >= 5:
                        ent_year = int(time_str[1:5])
                        # Permitimos ±1 año
                        if abs(ent_year - int(year)) > 1:
                            continue
                except Exception:
                    pass

            return wikidata_id, entity

        return None
    except Exception as e:
        _log_wiki(f"[WIKI] Error buscando por título '{title}' en Wikidata: {e}")
        return None


def _extract_imdb_id_from_entity(entity: Dict[str, Any]) -> Optional[str]:
    claims = entity.get("claims", {})
    if "P345" not in claims:
        return None
    try:
        snak = claims["P345"][0]["mainsnak"]
        return snak["datavalue"]["value"]
    except Exception:
        return None


def _extract_wikipedia_title(entity: Dict[str, Any], language: str) -> Optional[str]:
    sitelinks = entity.get("sitelinks", {})
    key = f"{language}wiki"
    site = sitelinks.get(key)
    if site and "title" in site:
        return site["title"]
    return None


# --------------------------------------------------------------------
# API pública: get_movie_record
# --------------------------------------------------------------------


def get_movie_record(
    title: str,
    year: Optional[int] = None,
    imdb_id_hint: Optional[str] = None,
    language: str = "en",
) -> Optional[Dict[str, Any]]:
    """
    Devuelve un registro "tipo OMDb" enriquecido con metadata de Wikipedia/Wikidata,
    usando wiki_cache.json como master.

    Reglas clave:

      - Si NO hay imdb_id_hint:
          * SIEMPRE se consulta Wikidata para intentar obtener imdb_id.
          * Con ese imdb_id se completa vía OMDb (cache → API).

      - Si SÍ hay imdb_id_hint:
          * OMDB_RETRY_EMPTY_CACHE = False → no se consulta Wikidata
            (solo OMDb / omdb_cache).
          * OMDB_RETRY_EMPTY_CACHE = True  → sí se consulta Wikidata
            para enriquecer con __wiki.

      - Si existe entrada en wiki_cache:
          * Se devuelve directamente.
          * Si OMDB_RETRY_EMPTY_CACHE = True y no tiene ratings,
            se reintenta OMDb con el imdb_id y se actualiza wiki_cache.
    """
    _load_wiki_cache()

    norm_title = _normalize_title(title)
    base_cache_key: str
    if imdb_id_hint:
        base_cache_key = f"imdb:{imdb_id_hint.lower()}"
    else:
        base_cache_key = f"title:{year}:{norm_title}"

    _log_wiki(
        f"[WIKI] get_movie_record(title='{title}', year={year}, imdb_hint={imdb_id_hint}) "
        f"→ base_cache_key='{base_cache_key}'"
    )

    # ----------------------------------------------------------------
    # 0) HIT en wiki_cache
    # ----------------------------------------------------------------
    record = _wiki_cache.get(base_cache_key)
    if record is not None:
        _log_wiki(f"[WIKI] cache HIT para {base_cache_key}")

        if OMDB_RETRY_EMPTY_CACHE and is_omdb_data_empty_for_ratings(record):
            imdb_cached = record.get("imdbID") or (record.get("__wiki") or {}).get("imdb_id")
            if imdb_cached:
                _log_wiki(
                    f"[WIKI] Registro en wiki_cache sin ratings, reintentando OMDb "
                    f"con imdbID={imdb_cached}..."
                )
                refreshed = search_omdb_by_imdb_id(imdb_cached)
                if refreshed and refreshed.get("Response") == "True":
                    merged = dict(refreshed)
                    if "__wiki" in record:
                        merged["__wiki"] = record["__wiki"]
                    _wiki_cache[base_cache_key] = merged
                    _save_wiki_cache()
                    _log_wiki(
                        f"[WIKI] wiki_cache actualizada con datos OMDb para {base_cache_key}"
                    )
                    return merged

        return record

    _log_wiki(f"[WIKI] cache MISS para {base_cache_key}, resolviendo...")

    # ----------------------------------------------------------------
    # 1) Resolver Wikidata / imdb_id_final según reglas
    # ----------------------------------------------------------------
    wikidata_id: Optional[str] = None
    entity: Optional[Dict[str, Any]] = None
    imdb_id_from_wiki: Optional[str] = None
    wiki_title: Optional[str] = None
    source_lang = language

    # Caso: tenemos imdb_id_hint y NO queremos tocar Wikidata
    if imdb_id_hint and not OMDB_RETRY_EMPTY_CACHE:
        _log_wiki(
            "[WIKI] imdb_id_hint disponible y OMDB_RETRY_EMPTY_CACHE=False → "
            "saltando Wikidata."
        )
        imdb_id_final = imdb_id_hint
        wiki_meta: Dict[str, Any] = {}
    else:
        # 1a) Intentar por IMDb ID
        if imdb_id_hint:
            result = _wikidata_search_by_imdb(imdb_id_hint)
            if result:
                wikidata_id, entity = result
                imdb_id_from_wiki = _extract_imdb_id_from_entity(entity)
                wiki_title = (
                    _extract_wikipedia_title(entity, language)
                    or _extract_wikipedia_title(entity, "es")
                )
                _log_wiki(
                    f"[WIKI] Encontrado en Wikidata por IMDb ID {imdb_id_hint}: "
                    f"wikidata_id={wikidata_id}, imdb_id_wiki={imdb_id_from_wiki}, "
                    f"wikipedia_title='{wiki_title}'"
                )

        # 1b) Si no hay entidad aún, buscar por título + año
        if entity is None:
            for lang in (language, "es"):
                result = _wikidata_search_by_title(title, year, language=lang)
                if result:
                    wikidata_id, entity = result
                    imdb_id_from_wiki = _extract_imdb_id_from_entity(entity)
                    wiki_title = _extract_wikipedia_title(entity, lang)
                    source_lang = lang
                    _log_wiki(
                        "[WIKI] Encontrada película en Wikidata por título: "
                        f"wikidata_id={wikidata_id}, imdb_id_wiki={imdb_id_from_wiki}, "
                        f"wikipedia_title='{wiki_title}', lang={lang}"
                    )
                    break

        wiki_meta: Dict[str, Any] = {}
        if entity is not None:
            wiki_meta = {
                "wikidata_id": wikidata_id,
                "wikipedia_title": wiki_title,
                "source_lang": source_lang,
                "imdb_id": imdb_id_from_wiki or imdb_id_hint,
            }

        imdb_id_final = imdb_id_from_wiki or imdb_id_hint

    # ----------------------------------------------------------------
    # 2) Resolver datos OMDb
    # ----------------------------------------------------------------
    omdb_data: Optional[Dict[str, Any]] = None

    if imdb_id_final:
        omdb_data = search_omdb_by_imdb_id(imdb_id_final)
    else:
        omdb_data = search_omdb_with_candidates(title, year)

    # ----------------------------------------------------------------
    # 3) Construir registro final y guardar en wiki_cache
    # ----------------------------------------------------------------
    if omdb_data:
        record_out: Dict[str, Any] = dict(omdb_data)
        if imdb_id_final and not record_out.get("imdbID"):
            record_out["imdbID"] = imdb_id_final
    else:
        record_out = {
            "Title": title,
            "Year": str(year) if year is not None else None,
            "imdbID": imdb_id_final,
        }

    if wiki_meta:
        record_out["__wiki"] = wiki_meta

    # Clave preferente basada en imdbID, para reutilizar entre variantes de título
    if imdb_id_final:
        wiki_key = f"imdb:{imdb_id_final.lower()}"
    else:
        wiki_key = base_cache_key

    _wiki_cache[wiki_key] = record_out
    if wiki_key != base_cache_key:
        _wiki_cache[base_cache_key] = record_out

    _save_wiki_cache()

    _log_wiki(
        f"[WIKI] Registro maestro creado para {wiki_key}: "
        f"imdbID={record_out.get('imdbID')}, "
        f"wikidata_id={record_out.get('__wiki', {}).get('wikidata_id') if '__wiki' in record_out else None}"
    )

    return record_out