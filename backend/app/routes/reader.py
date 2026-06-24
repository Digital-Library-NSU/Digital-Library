import asyncio
from typing import List, Dict, Any, Literal, Tuple

from fastapi import HTTPException, Query
from fastapi.responses import Response
from fastapi.routing import APIRouter
from sqlalchemy import select

from app.config import IDX_CONTENT
from app.dtos.reader_dtos import (
    GetChaptersResponse,
    ChapterDto,
    InBookSearchResponseDTO,
    InBookSearchHitDTO,
)
from app.dtos.search_dtos import SnippetDTO
from app.integrations.database import get_db_session
from app.integrations.elasticsearch import es_post
from app.integrations.embed_model import _HAS_ST, encode_query
from app.integrations.object_storage import get_object_bytes, chapter_key
from app.integrations.orm import Book, Chapter
from app.utils.paragraph_extras import fetch_paragraph_extras
from app.utils.search_highlight import (
    CONTENT_HIT_SOURCE,
    canonical_highlight,
    resolve_hit_block_index,
    same_highlight,
)

router = APIRouter(prefix="/reader")

def _chapter_path(book_id: int, chapter_id: int | None) -> str:
    if chapter_id is None:
        return ""

    return f"/reader/{book_id}/{chapter_id}"


def _chapter_key(sn: SnippetDTO) -> str:
    if sn.chapter_id is not None:
        return f"id:{sn.chapter_id}"
    return sn.chapter_path or f"ord:{sn.chapter_ord}"


def _make_semantic_snippet(text: str | None, max_len: int = 220) -> str:
    if not text:
        return ""

    value = text.strip()
    if len(value) <= max_len:
        return value

    return value[: max_len - 1].rstrip() + "…"


async def _book_exists(book_id: int) -> bool:
    async with get_db_session() as db:
        result = await db.execute(select(Book.id).where(Book.id == book_id))
        return result.scalar_one_or_none() is not None


@router.get("/{book_id}/search", response_model=InBookSearchResponseDTO)
async def search_in_book(
    book_id: int,
    q: str = Query(..., description="Цитата/фраза для поиска внутри этой книги"),
    mode: Literal["fulltext", "semantic"] = Query("fulltext", description="Режим поиска внутри книги"),
    size: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    slop: int = Query(2, ge=0, le=20, description="slop для match_phrase"),
    min_score: float = Query(0.0, ge=0.0, description="Порог релевантности ES"),
    fuzzy_fallback: bool = Query(True, description="Если match_phrase не дал результатов — попробовать fuzzy match"),
):
    if not await _book_exists(book_id):
        raise HTTPException(404, "Not found!")

    content_filter: List[Dict[str, Any]] = [
        {"term": {"book_id": str(book_id)}}
    ]

    phrase_query: Dict[str, Any] = {
        "match_phrase": {
            "content": {
                "query": q,
                "slop": slop,
            }
        }
    }

    fuzzy_query: Dict[str, Any] = {
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

    async def _do_fulltext_search(must_query: Dict[str, Any]) -> Dict[str, Any]:
        body: Dict[str, Any] = {
            "from": offset,
            "size": size,
            "query": {
                "bool": {
                    "must": [must_query],
                    "filter": content_filter,
                }
            },
            "_source": CONTENT_HIT_SOURCE,
            "highlight": {
                "type": "fvh",
                "fields": {
                    "content": {
                        "fragment_size": 220,
                        "number_of_fragments": 1,
                        "highlight_query": must_query,
                    }
                },
            },
        }

        if min_score > 0:
            body["min_score"] = float(min_score)

        return await es_post(f"{IDX_CONTENT}/_search", body)

    async def _do_semantic_search() -> Dict[str, Any]:
        if not _HAS_ST:
            raise HTTPException(
                500, "sentence-transformers is not installed on the server"
            )

        try:
            qvec = await asyncio.to_thread(encode_query, q)
        except Exception as e:
            raise HTTPException(500, f"Encoder error: {e}")

        semantic_size = 5
        semantic_pool_size = max(semantic_size * 4, semantic_size + offset)
        body: Dict[str, Any] = {
            "from": offset,
            "size": semantic_pool_size,
            "knn": {
                "field": "content_vec",
                "query_vector": qvec,
                "k": semantic_pool_size,
                "num_candidates": max(100, semantic_pool_size * 20),
                "filter": {"bool": {"filter": content_filter}},
            },
            "_source": CONTENT_HIT_SOURCE,
        }

        return await es_post(f"{IDX_CONTENT}/_search", body)

    if mode == "semantic":
        res = await _do_semantic_search()
        hits_raw = res.get("hits", {}).get("hits", [])
    else:
        res = await _do_fulltext_search(phrase_query)
        hits_raw = res.get("hits", {}).get("hits", [])

        if fuzzy_fallback and not hits_raw:
            res = await _do_fulltext_search(fuzzy_query)
            hits_raw = res.get("hits", {}).get("hits", [])

    doc_ids = [h.get("_id") for h in hits_raw if h.get("_id")]
    para_extras = await fetch_paragraph_extras(doc_ids)

    hits_with_key: List[Tuple[InBookSearchHitDTO, str]] = []

    for h in hits_raw:
        src = h.get("_source", {}) or {}
        score = float(h.get("_score") or 0.0)
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

        chapter_path = _chapter_path(book_id, int(chapter_id)) if chapter_id is not None else ""

        hl_list = h.get("highlight", {}).get("content", [])
        snippet_html = hl_list[0] if hl_list else _make_semantic_snippet(src.get("content"))
        canon_hl = canonical_highlight(snippet_html)

        hit_block_index = (
            resolve_hit_block_index(src, snippet_html)
            if mode == "fulltext"
            else src.get("block_start")
        )

        snippet = SnippetDTO(
            doc_id=doc_id,
            chapter_id=int(chapter_id) if chapter_id is not None else None,
            chapter_ord=chapter_ord,
            chapter_path=chapter_path,
            chapter_title=extra.chapter_title if extra else None,
            snippet=snippet_html,

            block_start=extra.block_start if extra else src.get("block_start"),
            block_end=extra.block_end if extra else src.get("block_end"),
            hit_block_index=hit_block_index,
        )

        hits_with_key.append(
            (
                InBookSearchHitDTO(score=score, snippet=snippet),
                canon_hl,
            )
        )

    hits_with_key.sort(key=lambda x: x[0].score, reverse=True)

    kept: List[Tuple[InBookSearchHitDTO, str]] = []
    best_by_chapter_start: Dict[str, Dict[int, Tuple[InBookSearchHitDTO, str]]] = {}

    for hit, canon_hl in hits_with_key:
        sn = hit.snippet

        if sn.hit_block_index is None:
            kept.append((hit, canon_hl))
            continue

        ck = _chapter_key(sn)
        start = int(sn.hit_block_index)

        chapter_map = best_by_chapter_start.get(ck)
        if chapter_map is None:
            chapter_map = {}
            best_by_chapter_start[ck] = chapter_map

        same_block = chapter_map.get(start)
        if same_block is not None:
            continue

        for nearby_start in range(start - 2, start + 3):
            nearby = chapter_map.get(nearby_start)
            if nearby is not None and same_highlight(canon_hl, nearby[1]):
                break
        else:
            chapter_map[start] = (hit, canon_hl)
            kept.append((hit, canon_hl))
            continue

        continue

    hits = [h for (h, _) in kept]
    if mode == "semantic":
        hits = hits[:5]

    return InBookSearchResponseDTO(total=len(hits), hits=hits)


@router.get("/{book_id}/chapters")
async def get_chapters(book_id: int) -> GetChaptersResponse:
    async with get_db_session() as db_session:
        exists_result = await db_session.execute(
            select(Book.id).where(Book.id == book_id)
        )
        exists = exists_result.scalar_one_or_none()

        if exists is None:
            raise HTTPException(404, "Not found!")

        stmt = (
            select(Chapter.id, Chapter.title)
            .where(Chapter.book_id == book_id)
            .order_by(Chapter.ord)
        )

        result = await db_session.execute(stmt)

        chapters = [
            ChapterDto(chapter_id=chapter_id, title=title)
            for chapter_id, title in result.all()
        ]

        if chapters and (chapters[0].title or "").lower() == "cover":
            chapters = chapters[1:]

        return GetChaptersResponse(chapters=chapters)


@router.get("/{book_id}/{chapter_id}")
async def get_chapter(book_id: int, chapter_id: int) -> Response:
    key = chapter_key(book_id, chapter_id)

    try:
        data, content_type = await get_object_bytes(key)
    except FileNotFoundError:
        raise HTTPException(404, "Not found!")

    return Response(
        content=data,
        media_type=content_type or "application/xhtml+xml",
    )
