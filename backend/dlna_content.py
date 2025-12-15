from __future__ import annotations

import requests
import xml.etree.ElementTree as ET
from typing import Iterable

from backend import logger as _logger


DIDL_NS = {
    "didl": "urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/",
    "dc": "http://purl.org/dc/elements/1.1/",
    "upnp": "urn:schemas-upnp-org:metadata-1-0/upnp/",
}


class DLNAContainer:
    def __init__(self, object_id: str, title: str) -> None:
        self.object_id = object_id
        self.title = title


class DLNAItem:
    def __init__(self, object_id: str, title: str, resource: str) -> None:
        self.object_id = object_id
        self.title = title
        self.resource = resource


def browse(
    control_url: str,
    object_id: str = "0",
    browse_flag: str = "BrowseDirectChildren",
    start_index: int = 0,
    requested_count: int = 200,
) -> tuple[list[DLNAContainer], list[DLNAItem]]:
    """
    Ejecuta la acción Browse del servicio ContentDirectory.
    """
    headers = {
        "Content-Type": 'text/xml; charset="utf-8"',
        "SOAPACTION": '"urn:schemas-upnp-org:service:ContentDirectory:1#Browse"',
    }

    body = f"""<?xml version="1.0"?>
    <s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/"
                s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">
      <s:Body>
        <u:Browse xmlns:u="urn:schemas-upnp-org:service:ContentDirectory:1">
          <ObjectID>{object_id}</ObjectID>
          <BrowseFlag>{browse_flag}</BrowseFlag>
          <Filter>*</Filter>
          <StartingIndex>{start_index}</StartingIndex>
          <RequestedCount>{requested_count}</RequestedCount>
          <SortCriteria></SortCriteria>
        </u:Browse>
      </s:Body>
    </s:Envelope>
    """

    resp = requests.post(control_url, data=body, headers=headers, timeout=10)
    resp.raise_for_status()

    envelope = ET.fromstring(resp.text)
    result = envelope.find(".//Result")
    if result is None or result.text is None:
        return [], []

    didl = ET.fromstring(result.text)

    containers: list[DLNAContainer] = []
    items: list[DLNAItem] = []

    for container in didl.findall("didl:container", DIDL_NS):
        object_id = container.attrib.get("id")
        title_el = container.find("dc:title", DIDL_NS)
        if object_id and title_el is not None:
            containers.append(DLNAContainer(object_id, title_el.text or ""))

    for item in didl.findall("didl:item", DIDL_NS):
        object_id = item.attrib.get("id")
        title_el = item.find("dc:title", DIDL_NS)
        res_el = item.find("didl:res", DIDL_NS)
        if object_id and title_el is not None and res_el is not None:
            items.append(
                DLNAItem(
                    object_id=object_id,
                    title=title_el.text or "",
                    resource=res_el.text or "",
                )
            )

    return containers, items