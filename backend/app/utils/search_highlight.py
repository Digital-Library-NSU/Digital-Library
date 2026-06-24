import html as html_lib
import re
from typing import Any, Dict, Optional

_TAG_RE = re.compile(r"<[^>]+>")
_EM_RE = re.compile(r"(?is)<em>(.*?)</em>")
_WS_RE = re.compile(r"\s+")


CONTENT_HIT_SOURCE = [
    "book_id",
    "chapter_id",
    "chapter_ord",
    "content",
    "block_start",
    "block_end",
    "block_offsets",
]


def strip_html(value: str) -> str:
    value = html_lib.unescape(value or "")
    value = _TAG_RE.sub(" ", value)
    return _WS_RE.sub(" ", value).strip()


def first_em_text(snippet_html: str) -> str:
    match = _EM_RE.search(snippet_html or "")
    if not match:
        return ""

    return strip_html(match.group(1))


def canonical_highlight(html_snippet: str, max_len: int = 220) -> str:
    if not html_snippet:
        return ""

    s = _EM_RE.sub(r"@@\1@@", html_snippet)
    s = _TAG_RE.sub(" ", s)
    s = html_lib.unescape(s)
    s = s.replace("\u00a0", " ").lower()
    s = _WS_RE.sub(" ", s).strip()

    anchor = s.find("@@")
    if anchor != -1:
        s = s[anchor:]

    s = s.replace("@@", "")

    return s[:max_len].strip()


def same_highlight(a: str, b: str) -> bool:
    if not a or not b:
        return False
    if a == b:
        return True
    if a.startswith(b) or b.startswith(a):
        return True
    if a in b or b in a:
        return True
    return False


def resolve_hit_block_index(src: Dict[str, Any], snippet_html: str) -> Optional[int]:
    block_start = src.get("block_start")
    content = src.get("content") or ""
    block_offsets = src.get("block_offsets") or []

    highlighted = first_em_text(snippet_html)
    if not highlighted:
        return _safe_int(block_start)

    pos = content.find(highlighted)

    if pos < 0:
        pos = content.casefold().find(highlighted.casefold())

    if pos < 0:
        return _safe_int(block_start)

    for item in block_offsets:
        if not isinstance(item, dict):
            continue

        start = _safe_int(item.get("start"))
        end = _safe_int(item.get("end"))
        block_index = _safe_int(item.get("block_index"))

        if start is None or end is None or block_index is None:
            continue

        if start <= pos < end:
            return block_index

    return _safe_int(block_start)


def _safe_int(value: Any) -> Optional[int]:
    if value is None:
        return None

    try:
        return int(value)
    except (TypeError, ValueError):
        return None