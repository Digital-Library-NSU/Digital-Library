import xml.etree.ElementTree as ET
from typing import Dict, List, Optional, Tuple
import zipfile

from .covers import resolve_href_relative, pick_cover_href_from_opf
from .text_utils import norm_space


def parse_container_and_opf(z: zipfile.ZipFile) -> str:
    container_xml = z.read("META-INF/container.xml")
    root = ET.fromstring(container_xml)
    ns = {"c": "urn:oasis:names:tc:opendocument:xmlns:container"}
    rf = root.find(".//c:rootfile", ns)
    if rf is None:
        raise RuntimeError("rootfile not found in container.xml")
    return rf.attrib.get("full-path", "")


def parse_opf(z: zipfile.ZipFile, opf_path: str):
    opf_xml = z.read(opf_path)
    opf = ET.fromstring(opf_xml)
    ns = {
        "dc": "http://purl.org/dc/elements/1.1/",
        "opf": "http://www.idpf.org/2007/opf",
    }

    titles = [
        norm_space(el.text)
        for el in opf.findall(".//dc:title", ns)
        if el is not None and norm_space(el.text)
    ]
    title = titles[0] if titles else None

    def get_text(path: str) -> str:
        el = opf.find(path, ns)
        return norm_space(el.text) if el is not None and el.text else ""

    language = get_text(".//dc:language") or None
    publisher = get_text(".//dc:publisher") or None
    date_raw = get_text(".//dc:date") or ""
    description = get_text(".//dc:description") or None
    creators = [
        norm_space(el.text)
        for el in opf.findall(".//dc:creator", ns)
        if el is not None and norm_space(el.text)
    ]
    subjects = [
        norm_space(s.text)
        for s in opf.findall(".//dc:subject", ns)
        if s is not None and norm_space(s.text)
    ]

    identifiers = []
    for ide in opf.findall(".//dc:identifier", ns):
        txt = norm_space(ide.text) if ide is not None and ide.text else ""
        if txt:
            scheme = ide.attrib.get("{http://www.idpf.org/2007/opf}scheme", "") or ""
            identifiers.append(((scheme.upper() or "ID"), txt))

    # manifest
    mf_items: Dict[str, Tuple[str, Optional[str]]] = {}
    for it in opf.findall(".//{http://www.idpf.org/2007/opf}item"):
        it_id = it.attrib.get("id")
        href = it.attrib.get("href")
        media_type = it.attrib.get("media-type")
        if it_id and href:
            href_path = resolve_href_relative(opf_path, href)
            mf_items[it_id] = (href_path, media_type)

    cover_href = pick_cover_href_from_opf(z, opf, opf_path, mf_items)

    # spine
    spine: List[Tuple[str, Optional[str]]] = []
    for itref in opf.findall(".//{http://www.idpf.org/2007/opf}itemref"):
        ref = itref.attrib.get("idref")
        if ref and ref in mf_items:
            spine.append(mf_items[ref])

    return {
        "title": title,
        "creators": creators,
        "language": language,
        "publisher": publisher,
        "date_raw": date_raw,
        "description": description,
        "subjects": subjects,
        "identifiers": identifiers,
        "opf_path": opf_path,
        "manifest": mf_items,
        "spine": spine,
        "cover_href": cover_href,
    }
