# backend/wiki_client.py
from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional

import requests

# Fichero de caché local (mismo patrón que omdb_cache.json)
WIKI_CACHE_FILE = "wiki_cache.json"

# Estructura: { cache_key: { ...info... } }
wiki_cache: Dict[str, Dict[str, Any]] = {}


def _load_wiki_cache() -> None:
    """Carga wiki_cache desde disco si aún no se ha cargado."""
    global wiki_cache

    if wiki_cache:
        # Ya cargado
        return

    if not os.path.exists(WIKI_CACHE_FILE):
        wiki_cache = {}
        return

    try:
        with open(WIKI_CACHE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                wiki_cache = data
            else:
                wiki_cache = {}
    except Exception as e:
        print(f"WARN [wiki] No se pudo leer {WIKI_CACHE_FILE}: {e}")
        wiki_cache = {}


def _save_wiki_cache() -> None:
    """Persiste wiki_cache a disco (best-effort)."""
    try:
        with open(WIKI_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(wiki_cache, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"WARN [wiki] No se pudo escribir {WIKI_CACHE_FILE}: {e}")


def _make_cache_key(title: str, year: Optional[int], language: str) -> str:
    t = (title or "").strip().lower()
    y = str(year) if year is not None else ""
    lang = (language or "en").lower()
    return f"{lang}|{y}|{t}"


def _call_wikipedia_search(
    title: str,
    year: Optional[int],
    language: str = "en",
) -> Optional[Dict[str, Any]]:
    """
    Hace una búsqueda simple en la Wikipedia en 'language' y devuelve
    el mejor resultado de búsqueda (o None).

    Este paso NO sabe aún nada de Wikidata; solo obtiene pageid y título.
    """
    query = title.strip()
    if year:
        query = f"{query} {year}"

    url = f"https://{language}.wikipedia.org/w/api.php"
    params = {
        "action": "query",
        "list": "search",
        "srsearch": query,
        "srnamespace": 0,  # artículos normales
        "srlimit": 1,      # solo el mejor match
        "format": "json",
    }

    try:
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"WARN [wiki] Error en búsqueda Wikipedia para '{query}': {e}")
        return None

    search_results = (
        data.get("query", {}).get("search", [])
        if isinstance(data, dict)
        else []
    )
    if not search_results:
        return None

    best = search_results[0]
    pageid = best.get("pageid")
    title_found = best.get("title")
    if not pageid or not title_found:
        return None

    return {
        "pageid": pageid,
        "wikipedia_title": title_found,
    }


def _get_wikidata_id_from_pageid(
    pageid: int,
    language: str = "en",
) -> Optional[str]:
    """
    Dado un pageid de Wikipedia, obtiene el Wikidata Q-id asociado (p.ej. 'Q12345').
    """
    url = f"https://{language}.wikipedia.org/w/api.php"
    params = {
        "action": "query",
        "prop": "pageprops",
        "pageids": str(pageid),
        "format": "json",
    }

    try:
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"WARN [wiki] Error obteniendo pageprops para pageid={pageid}: {e}")
        return None

    pages = data.get("query", {}).get("pages", {})
    page = pages.get(str(pageid)) or {}
    pageprops = page.get("pageprops") or {}
    wikidata_id = pageprops.get("wikibase_item")

    if isinstance(wikidata_id, str) and wikidata_id.startswith("Q"):
        return wikidata_id

    return None


def _get_wikidata_movie_info(wikidata_id: str) -> Dict[str, Any]:
    """
    Llama a la API de Wikidata para obtener información básica de una película,
    en particular el imdb_id (propiedad P345) y el año si se puede deducir.

    Devuelve un dict con algunos campos útiles:
      {
        "wikidata_id": "Q12345",
        "imdb_id": "tt1234567" o None,
        "year": 1994 o None,
      }
    """
    out: Dict[str, Any] = {
        "wikidata_id": wikidata_id,
        "imdb_id": None,
        "year": None,
    }

    url = f"https://www.wikidata.org/wiki/Special:EntityData/{wikidata_id}.json"

    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"WARN [wiki] Error llamando a Wikidata para {wikidata_id}: {e}")
        return out

    entities = data.get("entities", {})
    entity = entities.get(wikidata_id) or {}
    claims = entity.get("claims") or {}

    # IMDb ID → propiedad P345
    imdb_id = None
    for claim in claims.get("P345", []):
        mainsnak = claim.get("mainsnak") or {}
        datavalue = mainsnak.get("datavalue") or {}
        value = datavalue.get("value")
        if isinstance(value, str) and value.startswith("tt"):
            imdb_id = value
            break

    out["imdb_id"] = imdb_id

    # Año aproximado → propiedad P577 (fecha de publicación)
    year = None
    for claim in claims.get("P577", []):
        mainsnak = claim.get("mainsnak") or {}
        datavalue = mainsnak.get("datavalue") or {}
        value = datavalue.get("value") or {}
        time_str = value.get("time")
        if isinstance(time_str, str) and len(time_str) >= 5:
            # formato típico: +1994-06-15T00:00:00Z
            try:
                year_candidate = int(time_str[1:5])
                year = year_candidate
                break
            except Exception:
                continue

    out["year"] = year
    return out


def find_movie_in_wikidata(
    title: str,
    year: Optional[int] = None,
    language: str = "en",
) -> Optional[Dict[str, Any]]:
    """
    Devuelve un diccionario con información básica para una película
    obtenida a través de Wikipedia/Wikidata.

    Ejemplo de resultado:
      {
        "imdb_id": "tt1234567" o None,
        "wikidata_id": "Q12345",
        "wikipedia_title": "The Lion King",
        "year": 1994,
      }

    Devuelve None si no encuentra nada razonable. El resultado (incluyendo
    el caso "sin imdb_id") se cachea en wiki_cache.json.
    """
    _load_wiki_cache()

    cache_key = _make_cache_key(title, year, language)
    if cache_key in wiki_cache:
        cached = wiki_cache[cache_key]
        # Permitimos que el caché contenga {} (no encontrado) o un dict completo
        if cached:
            return cached
        return None

    # 1) Buscar en Wikipedia
    search_info = _call_wikipedia_search(title, year, language=language)
    if not search_info:
        # Cacheamos "no encontrado" para no repetir llamadas
        wiki_cache[cache_key] = {}
        _save_wiki_cache()
        return None

    pageid = search_info["pageid"]
    wiki_title = search_info["wikipedia_title"]

    # 2) Obtener Wikidata ID
    wikidata_id = _get_wikidata_id_from_pageid(pageid, language=language)
    if not wikidata_id:
        result = {
            "imdb_id": None,
            "wikidata_id": None,
            "wikipedia_title": wiki_title,
            "year": year,
        }
        wiki_cache[cache_key] = result
        _save_wiki_cache()
        return result

    # 3) Consultar Wikidata para imdb_id y año
    wd_info = _get_wikidata_movie_info(wikidata_id)

    result = {
        "imdb_id": wd_info.get("imdb_id"),
        "wikidata_id": wikidata_id,
        "wikipedia_title": wiki_title,
        "year": wd_info.get("year") or year,
    }

    wiki_cache[cache_key] = result
    _save_wiki_cache()
    return result