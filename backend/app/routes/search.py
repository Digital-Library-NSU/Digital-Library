from pathlib import Path
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, Query, HTTPException

from app.config import IDX_CONTENT, IDX_META, BOOKS_CONTENT_DIR
from app.integrations.database import get_pg
from app.integrations.elasticsearch import es_post
from app.integrations.embed_model import _HAS_ST, encode_query
from app.dtos.books_dtos import BookCardDto
from app.dtos.search_dtos import (
    SnippetDTO,
    FullTextHitDTO,
    FullTextResponseDTO,
    SemanticHitDTO,
    SemanticResponseDTO,
)

router = APIRouter(prefix="/search")


BOOKS_ROOT = Path(BOOKS_CONTENT_DIR).expanduser() if BOOKS_CONTENT_DIR else None


def cover_path_for_book(book_id: int) -> Optional[str]:
    if not BOOKS_ROOT:
        return None

    base_dir = BOOKS_ROOT / str(book_id)
    for ext in (".jpg", ".jpeg", ".png", ".webp"):
        candidate = base_dir / f"cover{ext}"
        if candidate.exists():
            return str(candidate)
    return None


class ParagraphExtra:
    def __init__(
        self,
        book_id: Optional[int],
        chapter_id: Optional[int],
        chapter_ord: Optional[int],
        chapter_title: Optional[str],
    ):
        self.book_id = book_id
        self.chapter_id = chapter_id
        self.chapter_ord = chapter_ord
        self.chapter_title = chapter_title


def fetch_paragraph_extras(doc_ids: List[str]) -> Dict[str, ParagraphExtra]:
    if not doc_ids:
        return {}

    base_map: Dict[str, str] = {}
    base_ids: List[str] = []
    for d in doc_ids:
        parts = d.split(":")
        if len(parts) >= 4:
            base = ":".join(parts[:3])
        else:
            base = d
        base_map[d] = base
        if base not in base_ids:
            base_ids.append(base)

    conn = get_pg()
    q = """
      SELECT
        cp.es_doc_id,
        cp.book_id,
        cp.chapter_id,
        ec.ord,
        ec.title
      FROM content_paragraphs cp
      LEFT JOIN edition_chapters ec
        ON ec.id = cp.chapter_id
      WHERE cp.es_doc_id = ANY(%s)
    """
    with conn.cursor() as cur:
        cur.execute(q, (base_ids,))
        rows = cur.fetchall()

    by_base: Dict[str, ParagraphExtra] = {}
    for es_doc_id, book_id, chapter_id, ord_, title in rows:
        by_base[es_doc_id] = ParagraphExtra(
            book_id=int(book_id) if book_id is not None else None,
            chapter_id=int(chapter_id) if chapter_id is not None else None,
            chapter_ord=int(ord_) if ord_ is not None else None,
            chapter_title=title,
        )

    result: Dict[str, ParagraphExtra] = {}
    for orig, base in base_map.items():
        extra = by_base.get(base)
        if extra:
            result[orig] = extra
    return result


def fetch_books_by_ids(ids: List[int]) -> Dict[int, BookCardDto]:
    if not ids:
        return {}

    conn = get_pg()
    q = """
      WITH sel AS (
        SELECT UNNEST(%s::bigint[]) AS id
      )
      SELECT
        b.id,
        b.title,
        COALESCE(string_agg(a.name, ', ' ORDER BY ba.ord), '') AS authors
      FROM sel
      JOIN books b ON b.id = sel.id
      LEFT JOIN book_authors ba ON ba.book_id = b.id
      LEFT JOIN authors a ON a.id = ba.author_id
      GROUP BY b.id, b.title
    """

    with conn.cursor() as cur:
        cur.execute(q, (ids,))
        rows = cur.fetchall()

    by_id: Dict[int, BookCardDto] = {}
    for book_id, title, authors in rows:
        bid = int(book_id)
        cover_path = cover_path_for_book(bid)
        by_id[bid] = BookCardDto(
            book_id=bid,
            title=title,
            cover_path=cover_path,
            authors=authors or "",
        )
    return by_id


def _build_fallback_snippet(content: Optional[str], query: str, max_len: int = 220) -> str:
    if not content:
        return ""

    text = content.strip()
    if not text:
        return ""

    q_norm = query.strip()
    if not q_norm:
        snippet = text[:max_len]
        return snippet + ("…" if len(text) > max_len else "")

    low_text = text.lower()
    low_q = q_norm.lower()

    idx = low_text.find(low_q)
    if idx == -1:
        snippet = text[:max_len]
        return snippet + ("…" if len(text) > max_len else "")

    start = max(0, idx - 60)
    end = min(len(text), idx + len(q_norm) + 60)
    snippet = text[start:end]

    rel_idx = snippet.lower().find(low_q)
    if rel_idx != -1:
        before = snippet[:rel_idx]
        mid = snippet[rel_idx:rel_idx + len(q_norm)]
        after = snippet[rel_idx + len(q_norm):]
        snippet = f"{before}<em>{mid}</em>{after}"

    if start > 0:
        snippet = "…" + snippet
    if end < len(text):
        snippet = snippet + "…"

    return snippet


# ---------------- FULLTEXT ----------------


@router.get("/fulltext", response_model=FullTextResponseDTO)
def fulltext_search(
    q: str = Query(..., description="Поисковый запрос (название / автор / цитата)"),
    lang: Optional[str] = Query(None, description="Фильтр по языку книги"),
    size: int = Query(10, ge=1, le=50),
    offset: int = Query(0, ge=0),
):
    # ---------- 1. Поиск по метаданным ----------
    meta_must: List[Dict[str, Any]] = []
    meta_filter: List[Dict[str, Any]] = []

    if q:
        meta_must.append(
            {
                "multi_match": {
                    "query": q,
                    "type": "best_fields",
                    "fields": [
                        "title^4",
                        "title.ru^4",
                        "title.en^3",
                        "author_names^3",
                        "author_names.ru^3",
                        "author_names.en^2",
                        "subjects^2",
                        "description",
                        "description.ru",
                        "description.en",
                    ],
                    "operator": "and",
                    "fuzziness": "AUTO",
                    "prefix_length": 1,
                    "fuzzy_transpositions": True,
                }
            }
        )

    if lang:
        meta_filter.append({"term": {"lang": lang}})

    meta_body = {
        "from": 0,
        "size": size,
        "query": {
            "bool": {
                "must": meta_must or [{"match_all": {}}],
                "filter": meta_filter,
            }
        },
        "_source": ["book_id"],
    }

    meta_res = es_post(f"{IDX_META}/_search", meta_body)
    meta_hits_raw = meta_res.get("hits", {}).get("hits", [])

    meta_book_ids: List[int] = []
    for h in meta_hits_raw:
        src = h.get("_source", {})
        book_id = src.get("book_id") or h.get("_id")
        try:
            meta_book_ids.append(int(book_id))
        except (TypeError, ValueError):
            continue

    # ---------- 2. Поиск по цитатам ----------
    content_filter: List[Dict[str, Any]] = []
    if lang:
        content_filter.append({"term": {"lang": lang}})

    phrase_query = {
        "match_phrase": {
            "content": {
                "query": q,
                "slop": 2,
            }
        }
    }
    fuzzy_query = {
        "match": {
            "content": {
                "query": q,
                "operator": "and",
                "fuzziness": "AUTO",
                "minimum_should_match": "85%",
                "prefix_length": 1,
                "fuzzy_transpositions": True,
            }
        }
    }

    content_body = {
        "from": offset,
        "size": size,
        "query": {
            "bool": {
                "should": [phrase_query, fuzzy_query],
                "minimum_should_match": 1,
                **({"filter": content_filter} if content_filter else {}),
            }
        },
        "_source": [
            "book_id",
            "edition_id",
            "chapter_ord",
            "chapter_href",
            "content",
        ],
        "highlight": {
            "type": "fvh",
            "fields": {
                "content": {
                    "fragment_size": 220,
                    "number_of_fragments": 1,
                    "highlight_query": phrase_query,
                }
            },
        },
    }

    content_res = es_post(f"{IDX_CONTENT}/_search", content_body)
    content_hits_raw = content_res.get("hits", {}).get("hits", [])

    # ---------- 3. Дотягиваем карточки книг + extras по параграфам ----------
    all_book_ids: List[int] = []
    all_book_ids.extend(meta_book_ids)
    for h in content_hits_raw:
        src = h.get("_source", {})
        try:
            all_book_ids.append(int(src.get("book_id")))
        except (TypeError, ValueError):
            continue

    unique_ids = sorted({bid for bid in all_book_ids if isinstance(bid, int)})
    books_by_id = fetch_books_by_ids(unique_ids)

    doc_ids = [h.get("_id") for h in content_hits_raw if h.get("_id")]
    para_extras = fetch_paragraph_extras(doc_ids)

    # ---------- 4. DTO для хитов из метаданных ----------
    meta_hits: List[FullTextHitDTO] = []
    for h in meta_hits_raw:
        src = h.get("_source", {})
        es_score = float(h.get("_score") or 0.0)

        bid_raw = src.get("book_id") or h.get("_id")
        try:
            bid = int(bid_raw)
        except (TypeError, ValueError):
            continue

        book = books_by_id.get(bid)
        if not book:
            continue

        meta_hits.append(
            FullTextHitDTO(
                book=book,
                score=es_score,
                match_type="meta",
                snippet=None,
            )
        )

    # ---------- 5. DTO для хитов-цитат ----------
    quote_hits: List[FullTextHitDTO] = []
    for h in content_hits_raw:
        src = h.get("_source", {})
        es_score = float(h.get("_score") or 0.0)

        try:
            bid = int(src.get("book_id"))
        except (TypeError, ValueError):
            continue

        book = books_by_id.get(bid)
        if not book:
            continue

        hl_list = h.get("highlight", {}).get("content", [])
        if hl_list:
            snippet_html = hl_list[0]
        else:
            snippet_html = _build_fallback_snippet(src.get("content"), q)

        doc_id = h.get("_id")
        extra = para_extras.get(doc_id or "")

        chapter_ord = (
            extra.chapter_ord
            if extra and extra.chapter_ord is not None
            else int(src.get("chapter_ord") or 0)
        )

        if BOOKS_ROOT and extra and extra.chapter_id is not None:
            chapter_path = str(BOOKS_ROOT / str(book.book_id) / f"{extra.chapter_id}.xml")
        else:
            chapter_path = ""

        snippet_dto = SnippetDTO(
            doc_id=doc_id or "",
            edition_id=str(src.get("edition_id")),
            chapter_ord=chapter_ord,
            chapter_path=chapter_path,
            chapter_title=extra.chapter_title if extra else None,
            snippet=snippet_html,
        )

        quote_hits.append(
            FullTextHitDTO(
                book=book,
                score=es_score,
                match_type="quote",
                snippet=snippet_dto,
            )
        )

    # ---------- 6. Объединяем и сортируем ----------
    meta_hits_sorted = sorted(meta_hits, key=lambda x: x.score, reverse=True)
    quote_hits_sorted = sorted(quote_hits, key=lambda x: x.score, reverse=True)

    all_hits = meta_hits_sorted + quote_hits_sorted
    total = len(all_hits)

    all_hits = all_hits[:size]

    return FullTextResponseDTO(total=total, hits=all_hits)


# ---------------- SEMANTIC ----------------


@router.get("/semantic", response_model=SemanticResponseDTO)
def semantic_search(
    q: str = Query(..., description="Запрос для семантического поиска"),
    lang: Optional[str] = Query(
        None, description="Фильтр языка документа (keyword, например 'ru'|'en')"
    ),
    book_id: Optional[int] = Query(
        None, description="Фильтр по конкретной книге"
    ),
    size: int = Query(10, ge=1, le=100),
    offset: int = Query(0, ge=0),
    num_candidates: Optional[int] = Query(
        None,
        description="kNN кандидатов перед обрезкой size; по умолчанию size*50, минимум 100",
    ),
):
    if not _HAS_ST:
        raise HTTPException(
            500, "sentence-transformers is not installed on the server"
        )

    try:
        qvec = encode_query(q)
    except Exception as e:
        raise HTTPException(500, f"Encoder error: {e}")

    ncand = max(100, size * 50) if num_candidates is None else max(
        1, int(num_candidates)
    )

    filters: List[Dict[str, Any]] = []
    if lang:
        filters.append({"term": {"lang": lang}})
    if book_id is not None:
        filters.append({"term": {"book_id": str(book_id)}})

    body = {
        "from": offset,
        "size": size,
        "knn": {
            "field": "content_vec",
            "query_vector": qvec,
            "k": size + offset,
            "num_candidates": ncand,
            **({"filter": {"bool": {"filter": filters}}} if filters else {}),
        },
        "_source": [
            "book_id",
            "edition_id",
            "chapter_ord",
            "chapter_href",
            "title",
            "lang",
            "content",
        ],
    }

    res = es_post(f"{IDX_CONTENT}/_search", body)
    hits_raw = res.get("hits", {}).get("hits", [])

    # extras по doc_id
    doc_ids = [h.get("_id") for h in hits_raw if h.get("_id")]
    para_extras = fetch_paragraph_extras(doc_ids)

    book_ids: List[int] = []
    for h in hits_raw:
        src = h.get("_source", {})
        try:
            book_ids.append(int(src.get("book_id")))
        except Exception:
            pass

    books_by_id = fetch_books_by_ids(sorted({bid for bid in book_ids}))

    def _make_snippet(txt: Optional[str]) -> Optional[str]:
        if not txt:
            return None
        t = txt.strip()
        if len(t) <= 220:
            return t
        return t[:200].rstrip() + "…"

    hits: List[SemanticHitDTO] = []
    for h in hits_raw:
        src = h.get("_source", {})
        try:
            bid = int(src.get("book_id"))
        except Exception:
            continue

        book = books_by_id.get(bid)
        if not book:
            continue

        snippet_text = _make_snippet(src.get("content"))

        doc_id = h.get("_id")
        extra = para_extras.get(doc_id or "")

        chapter_ord = (
            extra.chapter_ord
            if extra and extra.chapter_ord is not None
            else int(src.get("chapter_ord") or 0)
        )

        if BOOKS_ROOT and extra and extra.chapter_id is not None:
            chapter_path = str(BOOKS_ROOT / str(book.book_id) / f"{extra.chapter_id}.xml")
        else:
            chapter_path = ""

        snippet_dto = SnippetDTO(
            doc_id=doc_id or "",
            edition_id=str(src.get("edition_id")),
            chapter_ord=chapter_ord,
            chapter_path=chapter_path,
            chapter_title=extra.chapter_title if extra else None,
            snippet=snippet_text or "",
        )

        hits.append(
            SemanticHitDTO(
                book=book,
                score=float(h.get("_score") or 0.0),
                snippet=snippet_dto,
            )
        )

    total = res.get("hits", {}).get("total", {}).get("value", len(hits))
    return SemanticResponseDTO(total=total, hits=hits)
