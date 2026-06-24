import asyncio
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, Query, HTTPException
from sqlalchemy import func, select

from app.config import IDX_CONTENT, IDX_META
from app.dtos.books_dtos import BookCardDto
from app.dtos.search_dtos import (
    SnippetDTO,
    FullTextHitDTO,
    FullTextResponseDTO,
    SemanticHitDTO,
    SemanticResponseDTO,
)
from app.integrations.database import get_db_session
from app.integrations.elasticsearch import es_post
from app.integrations.embed_model import _HAS_ST, encode_query
from app.integrations.object_storage import find_cover_key
from app.integrations.orm import Book, Review
from app.utils.paragraph_extras import fetch_paragraph_extras
from app.utils.search_highlight import CONTENT_HIT_SOURCE, resolve_hit_block_index

router = APIRouter(prefix="/search")


async def _get_cover_path(book_id: int) -> str | None:
    cover_key = await find_cover_key(book_id)

    if cover_key is None:
        return None

    return f"/books/{book_id}/cover"


async def fetch_books_by_ids(ids: List[int]) -> Dict[int, BookCardDto]:
    if not ids:
        return {}

    async with get_db_session() as db:
        stmt = (
            select(
                Book,
                func.avg(Review.rating).label("avg_rating"),
                func.count(Review.id).label("reviews_count"),
            )
            .outerjoin(Review, Review.book_id == Book.id)
            .where(Book.id.in_(ids))
            .group_by(Book.id)
        )
        result = await db.execute(stmt)
        rows = result.all()

    cover_paths = [
        await _get_cover_path(int(row.Book.id))
        for row in rows
    ]

    by_id: Dict[int, BookCardDto] = {}

    for idx, row in enumerate(rows):
        b = row.Book
        bid = int(b.id)
        by_id[bid] = BookCardDto(
            book_id=bid,
            title=b.title,
            cover_path=cover_paths[idx],
            authors=", ".join(b.authors or []),
            avg_rating=float(row.avg_rating) if row.avg_rating is not None else None,
            reviews_count=int(row.reviews_count),
        )

    return by_id


def _chapter_path(book_id: int, chapter_id: int | None) -> str:
    if chapter_id is None:
        return ""

    return f"/reader/{book_id}/{chapter_id}"


@router.get("/fulltext", response_model=FullTextResponseDTO)
async def fulltext_search(
    q: str = Query(..., description="Поисковый запрос (название / автор / цитата)"),
    lang: Optional[str] = Query(None, description="Фильтр по языку книги"),
    size: int = Query(10, ge=1, le=50),
    offset: int = Query(0, ge=0),
):
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
                    "fuzziness": "AUTO:5,8",
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
                "operator": "or",
                "fuzziness": "AUTO:5,8",
                "minimum_should_match": "3<75%",
                "prefix_length": 1,
                "fuzzy_transpositions": True,
            }
        }
    }

    books_aggs = {
        "books": {
            "cardinality": {"field": "book_id", "precision_threshold": 40000}
        }
    }

    content_body_phrase = {
        "from": offset,
        "size": size,
        "query": {
            "bool": {
                "must": [phrase_query],
                **({"filter": content_filter} if content_filter else {}),
            }
        },
        "collapse": {"field": "book_id"},
        "aggs": books_aggs,
        "_source": CONTENT_HIT_SOURCE,
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

    meta_res, content_res = await asyncio.gather(
        es_post(f"{IDX_META}/_search", meta_body),
        es_post(f"{IDX_CONTENT}/_search", content_body_phrase),
    )

    meta_hits_raw = meta_res.get("hits", {}).get("hits", [])
    content_hits_raw = content_res.get("hits", {}).get("hits", [])

    quote_total_books = (
        content_res.get("aggregations", {})
        .get("books", {})
        .get("value", 0)
    )

    if quote_total_books == 0:
        content_body_fuzzy = {
            "from": offset,
            "size": size,
            "query": {
                "bool": {
                    "must": [fuzzy_query],
                    **({"filter": content_filter} if content_filter else {}),
                }
            },
            "collapse": {"field": "book_id"},
            "aggs": books_aggs,
            "_source": CONTENT_HIT_SOURCE,
            "highlight": {
                "type": "fvh",
                "fields": {
                    "content": {
                        "fragment_size": 220,
                        "number_of_fragments": 1,
                        "highlight_query": fuzzy_query,
                    }
                },
            },
        }

        content_res = await es_post(f"{IDX_CONTENT}/_search", content_body_fuzzy)
        content_hits_raw = content_res.get("hits", {}).get("hits", [])

    meta_book_ids: List[int] = []
    for h in meta_hits_raw:
        src = h.get("_source", {})
        book_id = src.get("book_id") or h.get("_id")

        try:
            meta_book_ids.append(int(book_id))
        except (TypeError, ValueError):
            continue

    all_book_ids: List[int] = []
    all_book_ids.extend(meta_book_ids)

    for h in content_hits_raw:
        src = h.get("_source", {})
        try:
            all_book_ids.append(int(src.get("book_id")))
        except (TypeError, ValueError):
            continue

    unique_ids = sorted({bid for bid in all_book_ids if isinstance(bid, int)})
    doc_ids = [h.get("_id") for h in content_hits_raw if h.get("_id")]

    books_by_id, para_extras = await asyncio.gather(
        fetch_books_by_ids(unique_ids),
        fetch_paragraph_extras(doc_ids),
    )

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
        snippet_html = hl_list[0] if hl_list else ""

        doc_id = h.get("_id") or ""
        extra = para_extras.get(doc_id)

        chapter_id = (
            extra.chapter_id
            if extra and extra.chapter_id is not None
            else src.get("chapter_id")
        )

        chapter_ord = (
            extra.chapter_ord
            if extra and extra.chapter_ord is not None
            else int(src.get("chapter_ord") or 0)
        )

        chapter_path = _chapter_path(book.book_id, int(chapter_id)) if chapter_id is not None else ""

        snippet_dto = SnippetDTO(
            doc_id=doc_id,
            chapter_id=int(chapter_id) if chapter_id is not None else None,
            chapter_ord=chapter_ord,
            chapter_path=chapter_path,
            chapter_title=extra.chapter_title if extra else None,
            snippet=snippet_html,

            block_start=extra.block_start if extra else src.get("block_start"),
            block_end=extra.block_end if extra else src.get("block_end"),
            hit_block_index=resolve_hit_block_index(src, snippet_html),
        )

        quote_hits.append(
            FullTextHitDTO(
                book=book,
                score=es_score,
                match_type="quote",
                snippet=snippet_dto,
            )
        )

    meta_hits_sorted = sorted(meta_hits, key=lambda x: x.score, reverse=True)
    quote_hits_sorted = sorted(quote_hits, key=lambda x: x.score, reverse=True)

    merged: List[FullTextHitDTO] = []
    seen_books: set[int] = set()

    for h in meta_hits_sorted:
        bid = int(h.book.book_id)
        if bid in seen_books:
            continue

        merged.append(h)
        seen_books.add(bid)

    for h in quote_hits_sorted:
        bid = int(h.book.book_id)
        if bid in seen_books:
            continue

        merged.append(h)
        seen_books.add(bid)

    merged = merged[:size]

    return FullTextResponseDTO(total=len(merged), hits=merged)


@router.get("/semantic", response_model=SemanticResponseDTO)
async def semantic_search(
    q: str = Query(..., description="Запрос для семантического поиска"),
    lang: Optional[str] = Query(None, description="Фильтр языка документа"),
    book_id: Optional[int] = Query(None, description="Фильтр по конкретной книге"),
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
        qvec = await asyncio.to_thread(encode_query, q)
    except Exception as e:
        raise HTTPException(500, f"Encoder error: {e}")

    ncand = max(100, size * 50) if num_candidates is None else max(
        1, int(num_candidates)
    )

    meta_filters: List[Dict[str, Any]] = [{"exists": {"field": "book_vec"}}]

    if lang:
        meta_filters.append({"term": {"lang": lang}})

    if book_id is not None:
        meta_filters.append({"ids": {"values": [str(book_id)]}})

    meta_body = {
        "from": offset,
        "size": size,
        "knn": {
            "field": "book_vec",
            "query_vector": qvec,
            "k": size + offset,
            "num_candidates": ncand,
            "filter": {"bool": {"filter": meta_filters}},
        },
        "_source": ["book_id"],
    }

    meta_res = await es_post(f"{IDX_META}/_search", meta_body)
    meta_hits_raw = meta_res.get("hits", {}).get("hits", [])

    ranked_book_hits: List[tuple[int, float]] = []
    for h in meta_hits_raw:
        src = h.get("_source", {})
        try:
            bid = int(src.get("book_id") or h.get("_id"))
        except Exception:
            continue

        ranked_book_hits.append((bid, float(h.get("_score") or 0.0)))

    book_ids = [bid for bid, _score in ranked_book_hits]

    async def _best_snippet_for_book(bid: int) -> Dict[str, Any] | None:
        body = {
            "size": 1,
            "knn": {
                "field": "content_vec",
                "query_vector": qvec,
                "k": 1,
                "num_candidates": 100,
                "filter": {
                    "bool": {
                        "filter": [{"term": {"book_id": str(bid)}}],
                    }
                },
            },
            "_source": [
                "book_id",
                "chapter_id",
                "chapter_ord",
                "title",
                "lang",
                "content",
                "block_start",
                "block_end",
                "block_offsets",
            ],
        }
        res = await es_post(f"{IDX_CONTENT}/_search", body)
        hits = res.get("hits", {}).get("hits", [])
        return hits[0] if hits else None

    snippet_hits_raw = await asyncio.gather(
        *[_best_snippet_for_book(bid) for bid in book_ids]
    )
    snippet_hits_by_book: Dict[int, Dict[str, Any]] = {}
    doc_ids: List[str] = []

    for hit in snippet_hits_raw:
        if not hit:
            continue

        src = hit.get("_source", {})
        try:
            bid = int(src.get("book_id"))
        except Exception:
            continue

        snippet_hits_by_book[bid] = hit
        if hit.get("_id"):
            doc_ids.append(hit["_id"])

    books_by_id, para_extras = await asyncio.gather(
        fetch_books_by_ids(book_ids),
        fetch_paragraph_extras(doc_ids),
    )

    def _make_snippet(txt: Optional[str]) -> Optional[str]:
        if not txt:
            return None

        t = txt.strip()
        if len(t) <= 220:
            return t

        return t[:200].rstrip() + "…"

    hits: List[SemanticHitDTO] = []

    for bid, book_score in ranked_book_hits:
        h = snippet_hits_by_book.get(bid)
        if h is None:
            continue

        src = h.get("_source", {})

        book = books_by_id.get(bid)
        if not book:
            continue

        snippet_text = _make_snippet(src.get("content"))

        doc_id = h.get("_id") or ""
        extra = para_extras.get(doc_id)

        chapter_id = (
            extra.chapter_id
            if extra and extra.chapter_id is not None
            else src.get("chapter_id")
        )

        chapter_ord = (
            extra.chapter_ord
            if extra and extra.chapter_ord is not None
            else int(src.get("chapter_ord") or 0)
        )

        chapter_path = _chapter_path(book.book_id, int(chapter_id)) if chapter_id is not None else ""

        block_start = extra.block_start if extra else src.get("block_start")
        block_end = extra.block_end if extra else src.get("block_end")

        snippet_dto = SnippetDTO(
            doc_id=doc_id,
            chapter_id=int(chapter_id) if chapter_id is not None else None,
            chapter_ord=chapter_ord,
            chapter_path=chapter_path,
            chapter_title=extra.chapter_title if extra else None,
            snippet=snippet_text or "",

            block_start=block_start,
            block_end=block_end,
            hit_block_index=block_start,
        )

        hits.append(
            SemanticHitDTO(
                book=book,
                score=book_score,
                snippet=snippet_dto,
            )
        )

    return SemanticResponseDTO(total=len(hits), hits=hits)
