import re
import unicodedata
from dataclasses import dataclass
from typing import List, Tuple

from bs4 import BeautifulSoup


WORD_RE = re.compile(r"[^\W\d_]+", re.UNICODE)

INDEXED_TAGS = [
    "h1", "h2", "h3", "h4", "h5", "h6",
    "p",
    "li",
    "blockquote",
    "pre",
    "code",
]


@dataclass
class BlockSegment:
    block_index: int
    text: str


@dataclass
class TextBlock:
    kind: str
    text: str

    block_start: int
    block_end: int

    segments: List[BlockSegment]


def norm_space(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()


def strip_accents_lower(s: str) -> str:
    s = unicodedata.normalize("NFKC", s)
    return s.lower()


def html_to_text(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    for bad in soup(["script", "style"]):
        bad.decompose()
    text = soup.get_text(separator=" ").replace("\xa0", " ")
    return norm_space(text)


def tokenize_words(text: str) -> List[str]:
    text = strip_accents_lower(text)
    return WORD_RE.findall(text)


def _kind_for_tag(tag_name: str) -> str:
    t = tag_name.lower()
    if t in {"h1", "h2", "h3", "h4", "h5", "h6"}:
        return "heading"
    if t == "li":
        return "list"
    if t == "blockquote":
        return "blockquote"
    if t in {"pre", "code"}:
        return "pre"
    return "paragraph"


def html_to_indexed_blocks(html: str) -> Tuple[List[TextBlock], str]:
    soup = BeautifulSoup(html, "lxml")

    for bad in soup(["script", "style", "nav", "aside", "footer", "header"]):
        bad.decompose()

    for br in soup.find_all("br"):
        br.replace_with("\n")

    blocks: List[TextBlock] = []
    block_index = 0

    for el in soup.find_all(INDEXED_TAGS, recursive=True):
        txt = norm_space(el.get_text(" ").replace("\xa0", " "))
        if not txt:
            continue

        el["data-block-index"] = str(block_index)

        kind = _kind_for_tag(el.name)
        segment = BlockSegment(block_index=block_index, text=txt)

        blocks.append(
            TextBlock(
                kind=kind,
                text=txt,
                block_start=block_index,
                block_end=block_index,
                segments=[segment],
            )
        )

        block_index += 1

    if not blocks:
        text = html_to_text(html)
        if text:
            blocks = [
                TextBlock(
                    kind="paragraph",
                    text=text,
                    block_start=0,
                    block_end=0,
                    segments=[BlockSegment(block_index=0, text=text)],
                )
            ]

    return blocks, str(soup)


def coalesce_short_paragraphs(blocks: List[TextBlock], min_words: int) -> List[TextBlock]:
    out: List[TextBlock] = []

    buf_kind: str | None = None
    buf_segments: List[BlockSegment] = []
    buf_w = 0

    def flush():
        nonlocal buf_kind, buf_segments, buf_w
        if not buf_segments:
            return

        text = "\n\n".join(seg.text for seg in buf_segments)
        out.append(
            TextBlock(
                kind=buf_kind or "paragraph",
                text=norm_space(text),
                block_start=buf_segments[0].block_index,
                block_end=buf_segments[-1].block_index,
                segments=list(buf_segments),
            )
        )

        buf_kind = None
        buf_segments = []
        buf_w = 0

    for block in blocks:
        w = len(tokenize_words(block.text))

        if buf_w == 0:
            buf_kind = block.kind
            buf_segments = list(block.segments)
            buf_w = w
            continue

        if buf_w < min_words and block.kind != "heading":
            buf_segments.extend(block.segments)
            buf_w += w
        else:
            flush()
            buf_kind = block.kind
            buf_segments = list(block.segments)
            buf_w = w

    flush()
    return out


def paragraph_windows(blocks: List[TextBlock], window_size: int, stride: int):
    window_size = max(1, int(window_size))
    stride = max(1, int(stride))
    n = len(blocks)

    if n == 0:
        return []

    if window_size == 1:
        return [(i, i, [blocks[i]]) for i in range(0, n, stride)]

    out = []
    i = 0
    last = n - window_size

    while i <= last:
        out.append((i, i + window_size - 1, blocks[i: i + window_size]))
        i += stride

    return out


def build_window_content_and_offsets(win_blocks: List[TextBlock]):
    parts: List[str] = []
    offsets: List[dict] = []
    cursor = 0

    all_segments: List[BlockSegment] = []
    for block in win_blocks:
        all_segments.extend(block.segments)

    for idx, segment in enumerate(all_segments):
        if idx > 0:
            parts.append("\n\n")
            cursor += 2

        start = cursor
        parts.append(segment.text)
        cursor += len(segment.text)
        end = cursor

        offsets.append(
            {
                "block_index": segment.block_index,
                "start": start,
                "end": end,
            }
        )

    return "".join(parts), offsets


def split_by_words(text: str, max_words: int, overlap_words: int) -> List[str]:
    ws = tokenize_words(text)

    if len(ws) <= max_words:
        return [text]

    chunks, i = [], 0
    step = max(1, max_words - max(0, overlap_words))

    while i < len(ws):
        part = ws[i: i + max_words]
        if not part:
            break
        chunks.append(" ".join(part))
        i += step

    return chunks