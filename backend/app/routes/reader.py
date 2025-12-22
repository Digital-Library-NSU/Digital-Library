from fastapi.routing import APIRouter
from fastapi import HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy import select
from pathlib import Path
from typing import Optional, List, Dict, Any

from app.config import BOOKS_CONTENT_DIR, IDX_CONTENT
from app.dtos.reader_dtos import GetChaptersResponse, ChapterDto, InBookSearchResponseDTO, InBookSearchHitDTO
from app.dtos.search_dtos import SnippetDTO
from app.integrations.database import get_db_session
from app.integrations.orm import EditionChapter, Edition, ContentParagraph
from app.integrations.elasticsearch import es_post
from sqlalchemy.orm import joinedload

router = APIRouter(prefix="/reader")



BOOKS_ROOT = Path(BOOKS_CONTENT_DIR).expanduser() if BOOKS_CONTENT_DIR else None


def _chapter_file_exists(book_id: int, chapter_id: int) -> bool:
    if not BOOKS_ROOT:
        return False
    return (BOOKS_ROOT / str(book_id) / f"{chapter_id}.xml").exists()


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
        base = ":".join(parts[:3]) if len(parts) >= 4 else d
        base_map[d] = base
        if base not in base_ids:
            base_ids.append(base)

    with get_db_session() as db:
        stmt = (
            select(ContentParagraph)
            .where(ContentParagraph.es_doc_id.in_(base_ids))
            .options(joinedload(ContentParagraph.chapter))
        )
        rows = db.execute(stmt).scalars().all()

    by_base: Dict[str, ParagraphExtra] = {}
    for cp in rows:
        if not cp.es_doc_id:
            continue
        ch = cp.chapter
        by_base[cp.es_doc_id] = ParagraphExtra(
            book_id=int(cp.book_id) if cp.book_id is not None else None,
            chapter_id=int(cp.chapter_id) if cp.chapter_id is not None else None,
            chapter_ord=int(ch.ord) if (ch is not None and ch.ord is not None) else None,
            chapter_title=ch.title if ch is not None else None,
        )

    result: Dict[str, ParagraphExtra] = {}
    for orig, base in base_map.items():
        extra = by_base.get(base)
        if extra:
            result[orig] = extra

    return result



@router.get("/{book_id}/search", response_model=InBookSearchResponseDTO)
def search_in_book(
    book_id: int,
    q: str = Query(..., description="Цитата/фраза для поиска внутри этой книги"),
    size: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    slop: int = Query(2, ge=0, le=20, description="slop для match_phrase"),
    min_score: float = Query(0.0, ge=0.0, description="Порог релевантности ES (отсекает слабые совпадения)"),
    fuzzy_fallback: bool = Query(True, description="Если match_phrase не дал результатов — попробовать fuzzy match"),
):

    with get_db_session() as db:
        edition_id = db.execute(select(Edition.id).where(Edition.book_id == book_id)).scalar_one_or_none()
        if edition_id is None:
            raise HTTPException(404, "Not found!")


    content_filter: List[Dict[str, Any]] = [{"term": {"book_id": str(book_id)}}]

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

    base_source = [
        "book_id",
        "edition_id",
        "chapter_ord",
        "chapter_href",
        "content",
    ]

    def _do_es_search(must_query: Dict[str, Any]) -> Dict[str, Any]:
        body: Dict[str, Any] = {
            "from": offset,
            "size": size,
            "query": {
                "bool": {
                    "must": [must_query],
                    "filter": content_filter,
                }
            },
            "_source": base_source,
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
        return es_post(f"{IDX_CONTENT}/_search", body)


    res = _do_es_search(phrase_query)
    hits_raw = res.get("hits", {}).get("hits", [])


    if fuzzy_fallback and not hits_raw:
        res = _do_es_search(fuzzy_query)
        hits_raw = res.get("hits", {}).get("hits", [])

    doc_ids = [h.get("_id") for h in hits_raw if h.get("_id")]
    para_extras = fetch_paragraph_extras(doc_ids)


    hits: List[InBookSearchHitDTO] = []
    for h in hits_raw:
        src = h.get("_source", {}) or {}
        score = float(h.get("_score") or 0.0)

        doc_id = h.get("_id") or ""
        extra = para_extras.get(doc_id)

        chapter_ord = (
            extra.chapter_ord
            if extra and extra.chapter_ord is not None
            else int(src.get("chapter_ord") or 0)
        )

        chapter_path = ""
        if extra and extra.chapter_id is not None and _chapter_file_exists(book_id, extra.chapter_id):
            chapter_path = f"/books_content/{book_id}/{extra.chapter_id}.xml"

        hl_list = h.get("highlight", {}).get("content", [])
        snippet_html = hl_list[0] if hl_list else ""

        snippet = SnippetDTO(
            doc_id=doc_id,
            edition_id=str(src.get("edition_id")),
            chapter_ord=chapter_ord,
            chapter_path=chapter_path,
            chapter_title=extra.chapter_title if extra else None,
            snippet=snippet_html,
        )

        hits.append(InBookSearchHitDTO(score=score, snippet=snippet))

    hits.sort(key=lambda x: x.score, reverse=True)

    return InBookSearchResponseDTO(total=len(hits), hits=hits)



@router.get("/{book_id}/chapters")
def get_chapters(book_id: int) -> GetChaptersResponse:
    with get_db_session() as db_session:
        edition_id = db_session.execute(
            select(Edition.id).where(Edition.book_id == book_id)
        ).scalar_one_or_none()

        if edition_id is None:
            raise HTTPException(404, "Not found!")

        stmt = (
            select(EditionChapter.id, EditionChapter.title)
            .where(EditionChapter.edition_id == edition_id)
            .order_by(EditionChapter.ord)
        )

        result = db_session.execute(stmt).all()
        chapters = [
            ChapterDto(chapter_id=chapter_id, title=title)
            for chapter_id, title in result
        ]

        if chapters and (chapters[0].title or "").lower() == "cover":
            chapters = chapters[1:]

        return GetChaptersResponse(chapters=chapters)


@router.get("/{book_id}/{chapter_id}")
def get_chapter(book_id: int, chapter_id: int) -> FileResponse:
    path = Path(BOOKS_CONTENT_DIR + f"/{book_id}/{chapter_id}.xml")
    if not path.is_file():
        raise HTTPException(404, "Not found!")
    return FileResponse(path=path, media_type="application/xhtml+xml")



