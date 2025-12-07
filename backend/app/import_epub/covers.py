from pathlib import Path, PurePosixPath
from typing import Dict, List, Optional, Tuple

from bs4 import BeautifulSoup
import zipfile


def normalize_zip_path(path: str) -> str:
    p = PurePosixPath(path)
    parts: List[str] = []
    for part in p.parts:
        if part in ("", "."):
            continue
        if part == "..":
            if parts:
                parts.pop()
        else:
            parts.append(part)
    return PurePosixPath(*parts).as_posix()


def resolve_href_relative(opf_path: str, href: str) -> str:
    base = Path(opf_path).parent
    if str(base) not in ("", "."):
        raw = str(base / href)
    else:
        raw = href
    return normalize_zip_path(raw)


def find_cover_image_in_html(z: zipfile.ZipFile, html_path: str) -> Optional[str]:
    try:
        raw = z.read(html_path)
    except KeyError:
        return None

    try:
        soup = BeautifulSoup(raw, "lxml")
    except Exception:
        return None

    img = soup.find("img")
    if not img:
        return None

    src = img.get("src")
    if not src:
        return None

    html_dir = Path(html_path).parent
    if str(html_dir) not in ("", "."):
        img_path_raw = str(html_dir / src)
    else:
        img_path_raw = src

    return normalize_zip_path(img_path_raw)


def pick_cover_href_from_opf(
    z: zipfile.ZipFile,
    opf_root,
    opf_path: str,
    manifest_items: Dict[str, Tuple[str, Optional[str]]],
) -> Optional[str]:
    #Фолбеки выбора обложки из OPF
    ns_opf = "http://www.idpf.org/2007/opf"

    image_items: List[Tuple[str, str, Optional[str]]] = [
        (it_id, href, media)
        for it_id, (href, media) in manifest_items.items()
        if media and media.startswith("image")
    ]

    cover_href: Optional[str] = None

    # 1) <meta name="cover" content="ID">
    meta_cover = opf_root.find(f".//{{{ns_opf}}}meta[@name='cover']")
    if meta_cover is not None:
        cval = meta_cover.attrib.get("content")
        if cval:
            if cval in manifest_items:
                href_path, mtype = manifest_items[cval]
                if mtype and mtype.startswith("image"):
                    cover_href = href_path
                else:
                    cand = find_cover_image_in_html(z, href_path)
                    if cand:
                        cover_href = cand
            else:
                href_path = resolve_href_relative(opf_path, cval)
                cand = find_cover_image_in_html(z, href_path)
                if cand:
                    cover_href = cand

    # 2) properties="cover-image"
    if not cover_href:
        for it in opf_root.findall(f".//{{{ns_opf}}}item"):
            props = it.attrib.get("properties", "")
            if "cover-image" in props:
                href = it.attrib.get("href")
                if href:
                    cover_href = resolve_href_relative(opf_path, href)
                    break

    # 3) <guide><reference type="cover" ...>
    if not cover_href:
        guide = opf_root.find(f".//{{{ns_opf}}}guide")
        if guide is not None:
            for ref in guide.findall(f"{{{ns_opf}}}reference"):
                if ref.attrib.get("type") == "cover":
                    href = ref.attrib.get("href")
                    if href:
                        page_path = resolve_href_relative(opf_path, href)
                        cand = find_cover_image_in_html(z, page_path)
                        if cand:
                            cover_href = cand
                            break

    # 4) id/href содержит "cover"
    if not cover_href and image_items:
        for it_id, href, media in image_items:
            key = (it_id or "").lower() + " " + (href or "").lower()
            if "cover" in key:
                cover_href = href
                break

    # 5) первая картинка
    if not cover_href and image_items:
        _, href, _ = image_items[0]
        cover_href = href

    return cover_href
