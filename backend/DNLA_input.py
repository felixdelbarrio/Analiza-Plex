# backend/DNLA_input.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Literal, Optional


SourceType = Literal["plex", "dlna", "local", "other"]


@dataclass
class DNLAInput:
    """
    Modelo de dominio común para representar una película proveniente
    de DLNA (o cualquier otra fuente), antes de ser procesada por el
    analizador (OMDb, scoring, misidentificación, reporting).

    Este modelo permite desacoplar completamente el analizador de
    detalles específicos de Plex o DLNA.
    """

    # ------------------------------------------------------
    # Origen y agrupación
    # ------------------------------------------------------
    source: SourceType          # "plex", "dlna", "local", etc.
    library: str                # Nombre del contenedor / carpeta lógica

    # ------------------------------------------------------
    # Identidad básica
    # ------------------------------------------------------
    title: str
    year: Optional[int] = None

    # ------------------------------------------------------
    # Información de fichero
    # ------------------------------------------------------
    file_path: Optional[str] = None
    file_size_bytes: Optional[int] = None

    # ------------------------------------------------------
    # Pistas opcionales
    # ------------------------------------------------------
    imdb_id_hint: Optional[str] = None
    plex_guid: Optional[str] = None
    rating_key: Optional[str] = None
    thumb_url: Optional[str] = None

    # ------------------------------------------------------
    # Extensión flexible
    # ------------------------------------------------------
    extra: Dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------
    # Utilidad
    # ------------------------------------------------------
    def as_basic_dict(self) -> Dict[str, Any]:
        """
        Devuelve un dict con la información esencial
        (útil para logs y debugging).
        """
        return {
            "source": self.source,
            "library": self.library,
            "title": self.title,
            "year": self.year,
            "file_path": self.file_path,
            "file_size_bytes": self.file_size_bytes,
            "imdb_id_hint": self.imdb_id_hint,
            "plex_guid": self.plex_guid,
            "rating_key": self.rating_key,
            "thumb_url": self.thumb_url,
            "extra": self.extra,
        }