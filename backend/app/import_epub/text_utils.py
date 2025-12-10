import re
import unicodedata
from typing import List, Tuple

from bs4 import BeautifulSoup


WORD_RE = re.compile(r"[^\W\d_]+", re.UNICODE)


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


def html_to_paragraph_blocks(html: str) -> List[Tuple[str, str]]:
    soup = BeautifulSoup(html, "lxml")
    for bad in soup(["script", "style", "nav", "aside", "footer", "header"]):
        bad.decompose()
    for br in soup.find_all("br"):
        br.replace_with("\n")

    blocks: List[Tuple[str, str]] = []
    tags = ["h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "blockquote", "pre", "code"]
    for el in soup.find_all(tags, recursive=True):
        txt = norm_space(el.get_text(" ").replace("\xa0", " "))
        if not txt:
            continue
        t = el.name.lower()
        if t in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            kind = "heading"
        elif t == "li":
            kind = "list"
        elif t == "blockquote":
            kind = "blockquote"
        elif t in {"pre", "code"}:
            kind = "pre"
        else:
            kind = "paragraph"
        blocks.append((kind, txt))

    if not blocks:
        text = html_to_text(html)
        paras = [norm_space(p) for p in re.split(r"\n{2,}", text) if norm_space(p)]
        blocks = [("paragraph", p) for p in paras]

    return blocks


def coalesce_short_paragraphs(blocks: List[Tuple[str, str]], min_words: int) -> List[Tuple[str, str]]:
    out: List[Tuple[str, str]] = []
    buf_type, buf_txt, buf_w = None, "", 0

    def flush():
        nonlocal buf_type, buf_txt, buf_w
        if buf_txt:
            out.append((buf_type or "paragraph", norm_space(buf_txt)))
        buf_type, buf_txt, buf_w = None, "", 0

    for kind, txt in blocks:
        w = len(tokenize_words(txt))
        if buf_w == 0:
            buf_type, buf_txt, buf_w = kind, txt, w
            continue
        if buf_w < min_words and kind != "heading":
            buf_txt = f"{buf_txt}\n\n{txt}"
            buf_w += w
        else:
            flush()
            buf_type, buf_txt, buf_w = kind, txt, w
    flush()
    return out


def paragraph_windows(blocks: List[Tuple[str, str]], window_size: int, stride: int):
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
        out.append((i, i + window_size - 1, blocks[i : i + window_size]))
        i += stride
    return out


def split_by_words(text: str, max_words: int, overlap_words: int) -> List[str]:
    ws = tokenize_words(text)
    if len(ws) <= max_words:
        return [text]
    chunks, i = [], 0
    step = max(1, max_words - max(0, overlap_words))
    while i < len(ws):
        part = ws[i : i + max_words]
        if not part:
            break
        chunks.append(" ".join(part))
        i += step
    return chunks
