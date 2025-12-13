# backend/plex_client.py
from typing import Any, Optional, Tuple

from plexapi.server import PlexServer

from backend.config import PLEX_BASEURL, PLEX_TOKEN
from backend import logger as _logger

# ============================================================
#                  LOGGING CONTROLADO POR SILENT_MODE
# ============================================================

def _log(msg: str) -> None:
    """Logea vía logger central con fallback ligero.

    Mantengo esta función local para compatibilidad con llamadas
    internas en este módulo.
    """
    try:
        _logger.info(str(msg))
    except Exception:
        # Fallback mínimo para entornos sin logger configurado
        print(msg)


# ============================================================
#                     CONEXIÓN A PLEX
# ============================================================

def connect_plex() -> PlexServer:
    """Crea y devuelve una instancia de `PlexServer` usando la configuración.

    Lanza RuntimeError si faltan variables de entorno o si la conexión falla.
    """
    if not PLEX_BASEURL or not PLEX_TOKEN:
        raise RuntimeError("Faltan PLEX_BASEURL o PLEX_TOKEN en el .env")

    _log(f"Conectando a Plex en {PLEX_BASEURL} ...")
    try:
        plex = PlexServer(PLEX_BASEURL, PLEX_TOKEN)
    except Exception as e:
        _log(f"ERROR conectando a Plex: {e}")
        raise
    _log("Conectado a Plex.")
    return plex


# ============================================================
#                  INFO DE ARCHIVOS DE PELÍCULAS
# ============================================================

def get_movie_file_info(movie: Any) -> Tuple[Optional[str], Optional[int]]:
    """Devuelve (ruta_principal, tamaño_total_en_bytes) para una película de Plex.

    Es defensiva: si la estructura del objeto Plex cambia o faltan atributos,
    devuelve (None, None).
    """
    media = getattr(movie, "media", None)
    if not media:
        return None, None

    total_size = 0
    main_path: Optional[str] = None

    for m in media:
        # `parts` puede no existir en algunas versiones/objetos
        parts = getattr(m, "parts", []) or []
        for p in parts:
            # Algunos objetos pueden exponer `file` como propiedad o método
            p_file = getattr(p, "file", None)
            p_size = getattr(p, "size", None)

            if p_file and not main_path:
                try:
                    main_path = str(p_file)
                except Exception:
                    main_path = None

            if isinstance(p_size, int):
                total_size += p_size

    if total_size <= 0:
        total_size = None

    return main_path, total_size


# ============================================================
#              EXTRACCIÓN DE IMDb ID DESDE GUIDS
# ============================================================

def get_imdb_id_from_plex_guid(guid: Optional[str]) -> Optional[str]:
    """Extrae el imdb_id (tt...) de un guid de Plex.

    Maneja formatos como:
      - com.plexapp.agents.imdb://tt1234567?lang=en
      - imdb://tt1234567
    """
    if not guid:
        return None

    s_guid = str(guid)
    # Buscar la primera aparición de 'tt' seguida de dígitos/alfanum
    pos = s_guid.find("tt")
    if pos == -1:
        return None

    s = s_guid[pos:]
    out_chars = []
    for ch in s:
        if ch.isalnum():
            out_chars.append(ch)
        else:
            break

    imdb_id = "".join(out_chars)
    if imdb_id.startswith("tt"):
        return imdb_id
    return None


def get_imdb_id_from_movie(movie: Any) -> Optional[str]:
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

def get_best_search_title(movie: Any) -> str:
    """Devuelve el mejor título estimado para buscar en OMDb.

    Preferimos `originalTitle` si existe y no está vacío, luego `title`.
    Siempre devolvemos una cadena (posiblemente vacía) para evitar excepciones
    en código que llama a esta función.
    """
    title = getattr(movie, "originalTitle", None)
    if isinstance(title, str) and title.strip():
        return title.strip()
    fallback = getattr(movie, "title", None)
    if isinstance(fallback, str):
        return fallback.strip()
    return ""