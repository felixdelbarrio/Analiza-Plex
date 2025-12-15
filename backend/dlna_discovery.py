from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple
import socket
import time
from urllib.parse import urlparse
from urllib.request import urlopen
import xml.etree.ElementTree as ET

from backend import logger as _logger


# Dirección multicast SSDP estándar
SSDP_ADDR: Tuple[str, int] = ("239.255.255.250", 1900)

# Intentamos primero el ST típico de MediaServer.
SSDP_ST_MEDIA_SERVER: str = "urn:schemas-upnp-org:device:MediaServer:1"

# Fallback genérico si el MediaServer ST no da resultados (algunos servers anuncian distinto).
SSDP_ST_ALL: str = "ssdp:all"

# MX: segundos máximos que los servidores pueden esperar antes de responder
SSDP_MX: int = 2

# Broadcast fallback (unicast) para redes donde multicast SSDP no funciona/está filtrado.
SSDP_BROADCAST_ADDR: Tuple[str, int] = ("255.255.255.255", 1900)

# Timeouts de red
LOCATION_FETCH_TIMEOUT_SECONDS: float = 5.0


@dataclass
class DLNADevice:
    friendly_name: str
    location: str
    host: str
    port: int


def _parse_ssdp_response(data: bytes) -> Dict[str, str]:
    """
    Parsea una respuesta SSDP (tipo cabeceras HTTP) a dict de headers en minúsculas.
    """
    try:
        text = data.decode("utf-8", errors="ignore")
    except Exception:
        return {}

    lines = text.split("\r\n")
    headers: Dict[str, str] = {}

    # Saltamos la primera línea "HTTP/1.1 200 OK"
    for line in lines[1:]:
        if not line.strip():
            continue
        if ":" not in line:
            continue
        name, value = line.split(":", 1)
        headers[name.strip().lower()] = value.strip()

    return headers


def _extract_friendly_name(root: ET.Element, fallback: str) -> str:
    """
    Extrae friendlyName del device description, tolerando XML con/sin namespaces.
    """
    # Sin namespaces:
    for dev in root.iter("device"):
        fn = dev.findtext("friendlyName")
        if fn:
            return fn.strip()

    # Con posibles namespaces (heurística mínima)
    for elem in root.iter():
        if isinstance(elem.tag, str) and elem.tag.endswith("device"):
            for child in elem:
                if isinstance(child.tag, str) and child.tag.endswith("friendlyName"):
                    if child.text:
                        return child.text.strip()

    return fallback


def _device_has_content_directory(root: ET.Element) -> bool:
    """
    Devuelve True si el device description contiene el servicio ContentDirectory.
    """
    for elem in root.iter():
        if not isinstance(elem.tag, str):
            continue
        if not elem.tag.endswith("service"):
            continue

        service_type: str | None = None
        for child in list(elem):
            if not isinstance(child.tag, str):
                continue
            if child.tag.endswith("serviceType") and child.text:
                service_type = child.text.strip()
                break

        if service_type and service_type.startswith(
            "urn:schemas-upnp-org:service:ContentDirectory:"
        ):
            return True

    return False


def _fetch_device_info(location: str) -> tuple[str, bool]:
    """
    Descarga la descripción del dispositivo UPnP (XML) desde LOCATION y
    devuelve (friendly_name, has_content_directory).

    Si falla, devuelve (LOCATION, False).
    """
    try:
        with urlopen(location, timeout=LOCATION_FETCH_TIMEOUT_SECONDS) as resp:
            xml_data = resp.read()
    except Exception as exc:  # pragma: no cover
        _logger.warning(f"[DLNA] No se pudo descargar LOCATION {location}: {exc}")
        return location, False

    try:
        root = ET.fromstring(xml_data)
    except Exception as exc:  # pragma: no cover
        _logger.warning(f"[DLNA] Error parseando XML de {location}: {exc}")
        return location, False

    friendly = _extract_friendly_name(root, fallback=location)
    has_cd = _device_has_content_directory(root)
    return friendly, has_cd


def _build_msearch(st: str, mx: int) -> bytes:
    """
    Construye un M-SEARCH SSDP.
    """
    msg = (
        "M-SEARCH * HTTP/1.1\r\n"
        f"HOST: {SSDP_ADDR[0]}:{SSDP_ADDR[1]}\r\n"
        'MAN: "ssdp:discover"\r\n'
        f"MX: {int(mx)}\r\n"
        f"ST: {st}\r\n"
        "\r\n"
    )
    return msg.encode("utf-8")


def _send_discovery_probes(sock: socket.socket, msg: bytes) -> None:
    """
    Envía probes SSDP por multicast y (fallback) por broadcast unicast.
    """
    # Multicast estándar
    try:
        sock.sendto(msg, SSDP_ADDR)
    except Exception:  # pragma: no cover
        pass

    # Broadcast unicast (útil cuando multicast está filtrado o no hay respuesta)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.sendto(msg, SSDP_BROADCAST_ADDR)
    except Exception:  # pragma: no cover
        pass


def discover_dlna_devices(
    timeout: float = 6.0,
    st: str = SSDP_ST_MEDIA_SERVER,
    mx: int = SSDP_MX,
) -> List[DLNADevice]:
    """
    Descubre dispositivos DLNA/UPnP en la red usando SSDP.

    IMPORTANTE:
    - Filtra para quedarse SOLO con dispositivos que realmente exponen ContentDirectory,
      evitando falsos positivos como routers IGD (p.ej. eero/igd.xml).
    - Además, envía M-SEARCH también por broadcast unicast (fallback), lo que ayuda
      en redes donde multicast no devuelve respuesta pero VLC sí detecta servidores.

    Devuelve una lista de DLNADevice con:
      - friendly_name
      - location (URL completa de descripción)
      - host
      - port

    Si no se encuentra ningún dispositivo con el ST indicado y éste no es
    "ssdp:all", se hace un reintento automático con ST="ssdp:all".
    """
    msg = _build_msearch(st=st, mx=mx)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    try:
        sock.settimeout(timeout)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        _send_discovery_probes(sock, msg)

        start = time.time()
        locations: Dict[str, DLNADevice] = {}

        while True:
            remaining = timeout - (time.time() - start)
            if remaining <= 0:
                break

            try:
                sock.settimeout(remaining)
                data, addr = sock.recvfrom(65535)
            except socket.timeout:
                break
            except Exception:  # pragma: no cover
                break

            headers = _parse_ssdp_response(data)
            loc = headers.get("location")
            if not loc:
                continue

            # Deduplicamos por LOCATION
            if loc in locations:
                continue

            parsed = urlparse(loc)
            host = parsed.hostname or addr[0]
            port = parsed.port or 80

            friendly, has_cd = _fetch_device_info(loc)

            # FILTRO CLAVE: sin ContentDirectory no es un MediaServer útil para nosotros
            if not has_cd:
                continue

            locations[loc] = DLNADevice(
                friendly_name=friendly,
                location=loc,
                host=host,
                port=port,
            )

        devices = list(locations.values())

        # Fallback: si no hay dispositivos y el ST no era ya "ssdp:all",
        # reintentamos una vez con ST genérico (pero seguimos filtrando por ContentDirectory).
        if not devices and st != SSDP_ST_ALL:
            _logger.info(
                f"[DLNA] Ningún dispositivo válido con ST={st!r}, "
                f"reintentando con ST={SSDP_ST_ALL!r}."
            )
            return discover_dlna_devices(timeout=timeout, st=SSDP_ST_ALL, mx=mx)

        _logger.info(
            f"[DLNA] Descubiertos {len(devices)} servidor(es) DLNA con ContentDirectory."
        )
        return devices
    finally:
        sock.close()