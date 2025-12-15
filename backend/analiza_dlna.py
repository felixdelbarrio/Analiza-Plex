from __future__ import annotations

"""
analiza_dlna.py

Flujo de análisis para contenidos obtenidos desde una fuente DLNA/UPnP real,
implementando browsing automático de ContentDirectory.

Este script:
  1. Recibe (opcionalmente) un DLNADevice ya seleccionado. Si no, descubre y permite seleccionar.
  2. Descarga el device description (LOCATION) y localiza el servicio ContentDirectory (controlURL).
  3. Obtiene contenedores (carpetas) de primer nivel vía Browse(ObjectID=0).
  4. Muestra menú:
       1) Todos (lista carpetas detectadas)
       2) Algunos (usuario indica carpetas separadas por comas)
  5. Recorre recursivamente contenedores seleccionados para obtener items (vídeos).
  6. Para cada item construye MovieInput y ejecuta analyze_input_movie.
  7. Enriquecimiento adicional para reporting/dashboard (poster_url, omdb_json, etc.)
  8. Escribe:
       - un CSV completo (todas las filas)
       - un CSV filtrado (DELETE / MAYBE)
       - un CSV de sugerencias de metadata vacío (compatibilidad dashboard)
"""

import json
from dataclasses import dataclass
from html import unescape
from typing import Mapping
from urllib.parse import urljoin
import xml.etree.ElementTree as ET

import requests

from backend import logger as _logger
from backend.analyze_input_core import analyze_input_movie
from backend.config import EXCLUDE_DLNA_LIBRARIES, METADATA_OUTPUT_PREFIX, OUTPUT_PREFIX
from backend.decision_logic import sort_filtered_rows
from backend.dlna_discovery import DLNADevice, discover_dlna_devices
from backend.movie_input import MovieInput
from backend.reporting import write_all_csv, write_filtered_csv, write_suggestions_csv
from backend.wiki_client import get_movie_record


_SOAP_ENV_NS = "http://schemas.xmlsoap.org/soap/envelope/"
_DIDL_NS = "urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/"
_DC_NS = "http://purl.org/dc/elements/1.1/"
_UPNP_NS = "urn:schemas-upnp-org:metadata-1-0/upnp/"

_NS = {
    "s": _SOAP_ENV_NS,
    "didl": _DIDL_NS,
    "dc": _DC_NS,
    "upnp": _UPNP_NS,
}

_CONTENT_DIRECTORY_PREFIX = "urn:schemas-upnp-org:service:ContentDirectory:"


@dataclass(frozen=True)
class _UPnPService:
    service_type: str
    control_url: str


@dataclass(frozen=True)
class _DLNAContainer:
    object_id: str
    title: str


@dataclass(frozen=True)
class _DLNAItem:
    object_id: str
    title: str
    resource_url: str | None
    upnp_class: str | None


def _select_dlna_device_interactively() -> DLNADevice | None:
    print("\nBuscando servidores DLNA/UPnP en la red...\n")
    devices = discover_dlna_devices()

    if not devices:
        _logger.error("No se han encontrado servidores DLNA/UPnP.", always=True)
        return None

    print("Se han encontrado los siguientes servidores DLNA/UPnP:\n")
    for idx, dev in enumerate(devices, start=1):
        print(f"  {idx}) {dev.friendly_name} ({dev.host}:{dev.port})")
        print(f"      LOCATION: {dev.location}")

    while True:
        raw = input(
            f"\nSelecciona un servidor (1-{len(devices)}) "
            "o pulsa Enter para cancelar: "
        ).strip()

        if raw == "":
            _logger.info("[DLNA] Operación cancelada (sin servidor).", always=True)
            return None

        if raw.isdigit():
            num = int(raw)
            if 1 <= num <= len(devices):
                chosen = devices[num - 1]
                print(
                    f"\nHas seleccionado: {chosen.friendly_name} "
                    f"({chosen.host}:{chosen.port})\n"
                )
                return chosen

        print(
            f"Opción no válida. Introduce un número entre 1 y {len(devices)}, "
            "o Enter para cancelar."
        )


def _fetch_device_description_xml(location_url: str) -> bytes | None:
    try:
        resp = requests.get(location_url, timeout=8)
        resp.raise_for_status()
        return resp.content
    except Exception as exc:  # pragma: no cover
        _logger.error(
            f"[DLNA] No se pudo descargar la descripción del dispositivo: {exc}",
            always=True,
        )
        return None


def _find_content_directory_service(
    device_description_xml: bytes,
    base_location_url: str,
) -> _UPnPService | None:
    try:
        root = ET.fromstring(device_description_xml)
    except Exception as exc:  # pragma: no cover
        _logger.error(f"[DLNA] XML inválido en device description: {exc}", always=True)
        return None

    for elem in root.iter():
        if not isinstance(elem.tag, str):
            continue
        if not elem.tag.endswith("service"):
            continue

        service_type: str | None = None
        control_url: str | None = None

        for child in list(elem):
            if not isinstance(child.tag, str):
                continue
            if child.tag.endswith("serviceType"):
                if child.text:
                    service_type = child.text.strip()
            elif child.tag.endswith("controlURL"):
                if child.text:
                    control_url = child.text.strip()

        if (
            service_type is not None
            and control_url is not None
            and service_type.startswith(_CONTENT_DIRECTORY_PREFIX)
        ):
            absolute_control_url = urljoin(base_location_url, control_url)
            return _UPnPService(service_type=service_type, control_url=absolute_control_url)

    return None


def _soap_browse(
    control_url: str,
    object_id: str,
    starting_index: int,
    requested_count: int,
) -> tuple[list[_DLNAContainer], list[_DLNAItem], int]:
    headers = {
        "Content-Type": 'text/xml; charset="utf-8"',
        "SOAPACTION": '"urn:schemas-upnp-org:service:ContentDirectory:1#Browse"',
    }

    body = f"""<?xml version="1.0" encoding="utf-8"?>
<s:Envelope xmlns:s="{_SOAP_ENV_NS}" s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">
  <s:Body>
    <u:Browse xmlns:u="urn:schemas-upnp-org:service:ContentDirectory:1">
      <ObjectID>{object_id}</ObjectID>
      <BrowseFlag>BrowseDirectChildren</BrowseFlag>
      <Filter>*</Filter>
      <StartingIndex>{starting_index}</StartingIndex>
      <RequestedCount>{requested_count}</RequestedCount>
      <SortCriteria></SortCriteria>
    </u:Browse>
  </s:Body>
</s:Envelope>
"""

    resp = requests.post(control_url, data=body, headers=headers, timeout=12)
    resp.raise_for_status()

    envelope = ET.fromstring(resp.text)

    result_el = envelope.find(".//Result")
    total_el = envelope.find(".//TotalMatches")

    total_matches = 0
    if total_el is not None and total_el.text and total_el.text.strip().isdigit():
        total_matches = int(total_el.text.strip())

    if result_el is None or result_el.text is None or not result_el.text.strip():
        return [], [], total_matches

    didl_text = result_el.text.strip()

    try:
        didl_root = ET.fromstring(didl_text)
    except Exception:
        didl_root = ET.fromstring(unescape(didl_text))

    containers: list[_DLNAContainer] = []
    items: list[_DLNAItem] = []

    for c in didl_root.findall("didl:container", _NS):
        obj_id = c.attrib.get("id")
        title_el = c.find("dc:title", _NS)
        title = title_el.text.strip() if title_el is not None and title_el.text else ""
        if obj_id:
            containers.append(_DLNAContainer(object_id=obj_id, title=title))

    for it in didl_root.findall("didl:item", _NS):
        obj_id = it.attrib.get("id")
        title_el = it.find("dc:title", _NS)
        title = title_el.text.strip() if title_el is not None and title_el.text else ""

        class_el = it.find("upnp:class", _NS)
        upnp_class = class_el.text.strip() if class_el is not None and class_el.text else None

        res_el = it.find("didl:res", _NS)
        resource_url = res_el.text.strip() if res_el is not None and res_el.text else None

        if obj_id:
            items.append(
                _DLNAItem(
                    object_id=obj_id,
                    title=title,
                    resource_url=resource_url,
                    upnp_class=upnp_class,
                )
            )

    return containers, items, total_matches


def _browse_all_children(
    control_url: str,
    object_id: str,
    page_size: int = 200,
) -> tuple[list[_DLNAContainer], list[_DLNAItem]]:
    all_containers: list[_DLNAContainer] = []
    all_items: list[_DLNAItem] = []

    start = 0
    total: int | None = None

    while True:
        containers, items, total_matches = _soap_browse(
            control_url=control_url,
            object_id=object_id,
            starting_index=start,
            requested_count=page_size,
        )
        all_containers.extend(containers)
        all_items.extend(items)

        if total is None:
            total = total_matches if total_matches > 0 else None

        got = len(containers) + len(items)
        if got <= 0:
            break

        start += got
        if total is not None and start >= total:
            break

    return all_containers, all_items


def _is_video_item(item: _DLNAItem) -> bool:
    if item.upnp_class and "videoItem" in item.upnp_class:
        return True
    return bool(item.resource_url)


def _select_top_level_containers(
    containers: list[_DLNAContainer],
) -> list[_DLNAContainer] | None:
    names_display = ", ".join(c.title for c in containers)

    print("\nSelecciona qué directorios analizar:")
    print(f"1) Todos ({names_display})")
    print("2) Algunos (indica, separados por comas, qué directorios analizar)")

    while True:
        choice = input("Opción (1-2) o Enter para cancelar: ").strip()

        if choice == "":
            _logger.info("[DLNA] Operación cancelada por el usuario.", always=True)
            return None

        if choice == "1":
            return containers

        if choice == "2":
            raw = input(
                "Introduce los directorios a analizar (separados por comas): "
            ).strip()
            wanted = [x.strip() for x in raw.split(",") if x.strip()]
            if not wanted:
                _logger.warning("No se indicó ningún directorio.", always=True)
                continue

            by_title = {c.title.lower(): c for c in containers}
            selected: list[_DLNAContainer] = []
            unknown: list[str] = []

            for name in wanted:
                c = by_title.get(name.lower())
                if c is None:
                    unknown.append(name)
                else:
                    selected.append(c)

            if unknown:
                _logger.warning(
                    "Directorios no encontrados: " + ", ".join(unknown),
                    always=True,
                )
                continue

            if not selected:
                _logger.warning("No se seleccionó ningún directorio válido.", always=True)
                continue

            # Sin duplicados preservando orden
            seen: set[str] = set()
            unique: list[_DLNAContainer] = []
            for c in selected:
                key = c.title.lower()
                if key in seen:
                    continue
                seen.add(key)
                unique.append(c)

            return unique

        _logger.warning("Opción no válida. Introduce 1, 2 o Enter.", always=True)


def _guess_title_year_from_title(title: str) -> tuple[str, int | None]:
    raw = title.strip()
    if not raw:
        return "", None

    if "(" in raw and ")" in raw:
        before, _, after = raw.partition("(")
        maybe_year, _, _ = after.partition(")")
        maybe_year = maybe_year.strip()
        if len(maybe_year) == 4 and maybe_year.isdigit():
            year_int = int(maybe_year)
            if 1900 <= year_int <= 2100:
                return before.strip(), year_int

    tokens = raw.replace(".", " ").replace("_", " ").split()
    for t in tokens:
        if len(t) == 4 and t.isdigit():
            year_int = int(t)
            if 1900 <= year_int <= 2100:
                return raw, year_int

    return raw, None


def analyze_dlna_server(device: DLNADevice | None = None) -> None:
    if device is None:
        device = _select_dlna_device_interactively()
        if device is None:
            return

    library = device.friendly_name

    if library in EXCLUDE_DLNA_LIBRARIES:
        _logger.info(
            f"[DLNA] La biblioteca '{library}' está en EXCLUDE_DLNA_LIBRARIES; "
            "se omite el análisis.",
            always=True,
        )
        return

    xml_bytes = _fetch_device_description_xml(device.location)
    if xml_bytes is None:
        return

    service = _find_content_directory_service(xml_bytes, device.location)
    if service is None:
        _logger.error(
            "[DLNA] El dispositivo no expone el servicio ContentDirectory.",
            always=True,
        )
        return

    _logger.info(
        f"[DLNA] ContentDirectory controlURL: {service.control_url}",
        always=True,
    )

    top_containers, top_items = _browse_all_children(service.control_url, object_id="0")

    selected_containers: list[_DLNAContainer] = []
    if top_containers:
        chosen = _select_top_level_containers(top_containers)
        if chosen is None:
            return
        selected_containers = chosen
    else:
        _logger.warning(
            "[DLNA] No se han encontrado contenedores en el nivel raíz. "
            "Se analizarán items directos si existen.",
            always=True,
        )

    items_to_analyze: list[_DLNAItem] = []

    if selected_containers:
        stack: list[_DLNAContainer] = list(selected_containers)
        while stack:
            container = stack.pop()
            children_containers, children_items = _browse_all_children(
                service.control_url, object_id=container.object_id
            )

            for it in children_items:
                if _is_video_item(it):
                    items_to_analyze.append(it)

            stack.extend(children_containers)
    else:
        for it in top_items:
            if _is_video_item(it):
                items_to_analyze.append(it)

    if not items_to_analyze:
        _logger.info("[DLNA] No se han encontrado items de vídeo para analizar.", always=True)
        return

    _logger.info(
        f"[DLNA] Se analizarán {len(items_to_analyze)} item(s) de vídeo.",
        always=True,
    )

    all_rows: list[dict[str, object]] = []
    suggestions_rows: list[dict[str, object]] = []

    for it in items_to_analyze:
        title, year = _guess_title_year_from_title(it.title)

        cached_omdb: dict[str, object] | None = None

        def fetch_omdb(title_for_fetch: str, year_for_fetch: int | None) -> Mapping[str, object]:
            nonlocal cached_omdb
            if cached_omdb is not None:
                return cached_omdb

            record = get_movie_record(
                title=title_for_fetch,
                year=year_for_fetch,
                imdb_id_hint=None,
            )
            if record is None:
                cached_omdb = {}
                return cached_omdb

            cached_omdb = dict(record) if isinstance(record, dict) else dict(record)
            return cached_omdb

        movie_input = MovieInput(
            source="dlna",
            library=library,
            title=title,
            year=year,
            file_path=it.resource_url or "",
            file_size_bytes=None,
            imdb_id_hint=None,
            plex_guid=None,
            rating_key=None,
            thumb_url=None,
            extra={},
        )

        try:
            base_row = analyze_input_movie(movie_input, fetch_omdb)
        except Exception as exc:  # pragma: no cover
            _logger.error(f"[DLNA] Error analizando item {it.title!r}: {exc}", always=True)
            continue

        if not base_row:
            _logger.warning(
                f"[DLNA] analyze_input_movie devolvió fila vacía para {it.title!r}",
                always=True,
            )
            continue

        row: dict[str, object] = dict(base_row)

        row["file"] = it.resource_url
        row["file_size"] = None

        omdb_data = dict(fetch_omdb(title, year))

        poster_url: str | None = None
        trailer_url: str | None = None
        imdb_id: str | None = None
        omdb_json_str: str | None = None
        wikidata_id: str | None = None
        wikipedia_title: str | None = None

        if omdb_data:
            poster_raw = omdb_data.get("Poster")
            trailer_raw = omdb_data.get("Website")
            imdb_id_raw = omdb_data.get("imdbID")

            if isinstance(poster_raw, str):
                poster_url = poster_raw
            if isinstance(trailer_raw, str):
                trailer_url = trailer_raw
            if isinstance(imdb_id_raw, str):
                imdb_id = imdb_id_raw

            try:
                omdb_json_str = json.dumps(omdb_data, ensure_ascii=False)
            except Exception:
                omdb_json_str = str(omdb_data)

            wiki_raw = omdb_data.get("__wiki")
            if isinstance(wiki_raw, dict):
                wikidata_val = wiki_raw.get("wikidata_id")
                wiki_title_val = wiki_raw.get("wikipedia_title")
                if isinstance(wikidata_val, str):
                    wikidata_id = wikidata_val
                if isinstance(wiki_title_val, str):
                    wikipedia_title = wiki_title_val

        row["poster_url"] = poster_url
        row["trailer_url"] = trailer_url
        row["imdb_id"] = imdb_id
        row["thumb"] = None
        row["omdb_json"] = omdb_json_str
        row["wikidata_id"] = wikidata_id
        row["wikipedia_title"] = wikipedia_title
        row["guid"] = None
        row["rating_key"] = None

        all_rows.append(row)

    if not all_rows:
        _logger.info("[DLNA] No se han generado filas de análisis.", always=True)
        return

    filtered_rows = [r for r in all_rows if r.get("decision") in {"DELETE", "MAYBE"}]
    filtered_rows = sort_filtered_rows(filtered_rows) if filtered_rows else []

    all_path = f"{OUTPUT_PREFIX}_dlna_all.csv"
    filtered_path = f"{OUTPUT_PREFIX}_dlna_filtered.csv"
    suggestions_path = f"{METADATA_OUTPUT_PREFIX}_dlna.csv"

    write_all_csv(all_path, all_rows)
    write_filtered_csv(filtered_path, filtered_rows)
    write_suggestions_csv(suggestions_path, suggestions_rows)

    _logger.info(
        f"[DLNA] Análisis completado. CSV completo: {all_path} | CSV filtrado: {filtered_path}",
        always=True,
    )


if __name__ == "__main__":
    analyze_dlna_server()