from dataclasses import dataclass
from typing import Optional, List, Dict

from sqlalchemy import select
from sqlalchemy.orm import joinedload

from app.integrations.database import get_db_session
from app.integrations.orm import ContentParagraph


@dataclass
class ParagraphExtra:
    book_id: Optional[int]
    chapter_id: Optional[int]
    chapter_ord: Optional[int]
    chapter_title: Optional[str]
    paragraph_id: Optional[int]

    block_start: Optional[int]
    block_end: Optional[int]


def _base_doc_id(doc_id: str) -> str:
    parts = doc_id.split(":")
    if len(parts) >= 4:
        return ":".join(parts[:3])
    return doc_id


async def fetch_paragraph_extras(doc_ids: List[str]) -> Dict[str, ParagraphExtra]:
    if not doc_ids:
        return {}

    base_map: Dict[str, str] = {}
    base_ids: List[str] = []

    for doc_id in doc_ids:
        base = _base_doc_id(doc_id)
        base_map[doc_id] = base
        if base not in base_ids:
            base_ids.append(base)

    async with get_db_session() as db:
        stmt = (
            select(ContentParagraph)
            .where(ContentParagraph.es_doc_id.in_(base_ids))
            .options(joinedload(ContentParagraph.chapter))
        )

        result = await db.execute(stmt)
        rows = result.scalars().all()

    by_base: Dict[str, ParagraphExtra] = {}

    for cp in rows:
        if not cp.es_doc_id:
            continue

        ch = cp.chapter

        by_base[cp.es_doc_id] = ParagraphExtra(
            book_id=int(cp.book_id) if cp.book_id is not None else None,
            chapter_id=int(cp.chapter_id) if cp.chapter_id is not None else None,
            chapter_ord=int(ch.ord) if ch is not None and ch.ord is not None else None,
            chapter_title=ch.title if ch is not None else None,
            paragraph_id=int(cp.id) if cp.id is not None else None,
            block_start=int(cp.block_start) if cp.block_start is not None else None,
            block_end=int(cp.block_end) if cp.block_end is not None else None,
        )

    result_map: Dict[str, ParagraphExtra] = {}

    for original_doc_id, base_doc_id in base_map.items():
        extra = by_base.get(base_doc_id)
        if extra:
            result_map[original_doc_id] = extra

    return result_map