from typing import Optional, Tuple

from plexapi.server import PlexServer

from backend.config import PLEX_BASEURL, PLEX_TOKEN


def connect_plex():
    """
    Crea y devuelve una instancia de PlexServer usando la configuración
    de backend.config. Mantiene los mismos mensajes por consola que
    la versión original en analiza_plex.py.
    """
    if not PLEX_BASEURL or not PLEX_TOKEN:
        raise RuntimeError("Faltan PLEX_BASEURL o PLEX_TOKEN en el .env")

    print(f"Conectando a Plex en {PLEX_BASEURL} ...")
    plex = PlexServer(PLEX_BASEURL, PLEX_TOKEN)
    print("Conectado a Plex.")
    return plex


def get_movie_file_info(movie) -> Tuple[Optional[str], Optional[int]]:
    """
    Devuelve (ruta_principal, tamaño_total_en_bytes) para una película
    de Plex. Copiado tal cual desde analiza_plex.py para no cambiar
    el comportamiento.
    """
    try:
        media = movie.media
    except Exception:
        media = None

    if not media:
        return None, None

    total_size = 0
    main_path: Optional[str] = None

    for m in media:
        parts = getattr(m, "parts", []) or []
        for p in parts:
            p_file = getattr(p, "file", None)
            p_size = getattr(p, "size", None)
            if p_file and not main_path:
                main_path = p_file
            if isinstance(p_size, int):
                total_size += p_size

    if total_size <= 0:
        total_size = None

    return main_path, total_size


def get_imdb_id_from_plex_guid(guid: str) -> Optional[str]:
    """
    Extrae el imdb_id (tt...) de un guid de Plex, si está presente.
    Misma lógica que en analiza_plex.py original.
    """
    if not guid:
        return None

    if "://tt" in guid:
        pos = guid.find("tt")
        if pos == -1:
            return None
        s = guid[pos:]
        out = []
        for ch in s:
            if ch.isalnum():
                out.append(ch)
            else:
                break
        imdb_id = "".join(out)
        if imdb_id.startswith("tt"):
            return imdb_id
        return None

    return None


def get_imdb_id_from_movie(movie) -> Optional[str]:
    """
    Intenta obtener un imdb_id (tt...) usando TODA la información
    de GUIDs de Plex:

      1) Recorre movie.guids (si existe) y busca un tt... en cada id.
      2) Si no encuentra nada, cae al guid principal (movie.guid)
         usando get_imdb_id_from_plex_guid, manteniendo el
         comportamiento histórico.

    Si no se consigue ningún imdb_id, devuelve None.
    """
    # 1) Revisar todos los guids individuales
    try:
        guids = getattr(movie, "guids", None) or []
        for g in guids:
            gid = getattr(g, "id", None)
            if not gid:
                gid = str(g)
            imdb_id = get_imdb_id_from_plex_guid(gid)
            if imdb_id:
                return imdb_id
    except Exception:
        # No queremos romper el análisis si Plex cambia algo
        pass

    # 2) Fallback al guid principal, como antes
    guid = getattr(movie, "guid", None)
    return get_imdb_id_from_plex_guid(guid or "")


def get_best_search_title(movie) -> str:
    """
    Devuelve el título preferido para buscar en OMDb:
    primero originalTitle si existe, si no title normal.
    """
    title = getattr(movie, "originalTitle", None)
    if title and isinstance(title, str) and title.strip():
        return title
    return movie.title