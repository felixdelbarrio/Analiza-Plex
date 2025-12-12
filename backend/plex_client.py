# backend/plex_client.py
from typing import Optional, Tuple

from plexapi.server import PlexServer

from backend.config import PLEX_BASEURL, PLEX_TOKEN, SILENT_MODE

# ============================================================
#                  LOGGING CONTROLADO POR SILENT_MODE
# ============================================================

def _log(msg: str) -> None:
    """
    Log controlado:
    - Si SILENT_MODE = True → NO imprime nada.
    - Si SILENT_MODE = False → imprime el mensaje.
    """
    if SILENT_MODE:
        return
    print(msg)


# ============================================================
#                     CONEXIÓN A PLEX
# ============================================================

def connect_plex():
    """
    Crea y devuelve una instancia de PlexServer usando la configuración.
    """
    if not PLEX_BASEURL or not PLEX_TOKEN:
        raise RuntimeError("Faltan PLEX_BASEURL o PLEX_TOKEN en el .env")

    _log(f"Conectando a Plex en {PLEX_BASEURL} ...")
    plex = PlexServer(PLEX_BASEURL, PLEX_TOKEN)
    _log("Conectado a Plex.")
    return plex


# ============================================================
#                  INFO DE ARCHIVOS DE PELÍCULAS
# ============================================================

def get_movie_file_info(movie) -> Tuple[Optional[str], Optional[int]]:
    """
    Devuelve (ruta_principal, tamaño_total_en_bytes) para una película de Plex.
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


# ============================================================
#              EXTRACCIÓN DE IMDb ID DESDE GUIDS
# ============================================================

def get_imdb_id_from_plex_guid(guid: str) -> Optional[str]:
    """
    Extrae el imdb_id (tt...) de un guid de Plex.
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


def get_imdb_id_from_movie(movie) -> Optional[str]:
    """
    Intenta obtener un imdb_id (tt...) usando toda la información de Plex:

    1) Recorre movie.guids para buscar tt...
    2) Si no encuentra nada, cae al guid principal (movie.guid).
    """
    # 1) Revisar todos los GUIDs individuales
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
        # Plex puede variar, no queremos romper nada
        pass

    # 2) Fallback al GUID principal
    guid = getattr(movie, "guid", None)
    return get_imdb_id_from_plex_guid(guid or "")


# ============================================================
#              OBTENER TÍTULO MÁS FIABLE PARA OMDb
# ============================================================

def get_best_search_title(movie) -> str:
    """
    Devuelve el mejor título estimado para buscar en OMDb.
    """
    title = getattr(movie, "originalTitle", None)
    if title and isinstance(title, str) and title.strip():
        return title
    return movie.title