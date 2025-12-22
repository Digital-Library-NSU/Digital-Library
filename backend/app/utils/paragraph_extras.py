from typing import Optional, List, Dict, Tuple, Any

from sqlalchemy import select
from sqlalchemy.orm import joinedload

from app.integrations.database import get_db_session
from app.integrations.orm import ContentParagraph


class ParagraphExtra:
    def __init__(
        self,
        book_id: Optional[int],
        chapter_id: Optional[int],
        chapter_ord: Optional[int],
        chapter_title: Optional[str],
        paragraph_id: Optional[int],
        para_start: Optional[int],
        para_end: Optional[int],
        para_index_in_chapter: Optional[int],
    ):
        self.book_id = book_id
        self.chapter_id = chapter_id
        self.chapter_ord = chapter_ord
        self.chapter_title = chapter_title
        self.paragraph_id = paragraph_id
        self.para_start = para_start
        self.para_end = para_end
        self.para_index_in_chapter = para_index_in_chapter


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

        chapter_ids = sorted({int(cp.chapter_id) for cp in rows if cp.chapter_id is not None})

        para_index_by_pair: Dict[Tuple[int, int], int] = {}
        if chapter_ids:
            all_stmt = (
                select(ContentParagraph.id, ContentParagraph.chapter_id)
                .where(ContentParagraph.chapter_id.in_(chapter_ids))
                .order_by(ContentParagraph.chapter_id, ContentParagraph.para_start, ContentParagraph.id)
            )
            all_rows = db.execute(all_stmt).all()

            last_ch: Optional[int] = None
            idx = 0
            for pid, ch_id in all_rows:
                if ch_id is None:
                    continue
                ch_int = int(ch_id)
                if last_ch is None or ch_int != last_ch:
                    last_ch = ch_int
                    idx = 0
                para_index_by_pair[(ch_int, int(pid))] = idx
                idx += 1

    by_base: Dict[str, ParagraphExtra] = {}
    for cp in rows:
        if not cp.es_doc_id:
            continue

        ch = cp.chapter
        ch_id_int = int(cp.chapter_id) if cp.chapter_id is not None else None
        pid_int = int(cp.id) if cp.id is not None else None

        para_idx = None
        if ch_id_int is not None and pid_int is not None:
            para_idx = para_index_by_pair.get((ch_id_int, pid_int))

        by_base[cp.es_doc_id] = ParagraphExtra(
            book_id=int(cp.book_id) if cp.book_id is not None else None,
            chapter_id=ch_id_int,
            chapter_ord=int(ch.ord) if (ch is not None and ch.ord is not None) else None,
            chapter_title=ch.title if ch is not None else None,
            paragraph_id=pid_int,
            para_start=int(cp.para_start) if cp.para_start is not None else None,
            para_end=int(cp.para_end) if cp.para_end is not None else None,
            para_index_in_chapter=para_idx,
        )

    result: Dict[str, ParagraphExtra] = {}
    for orig, base in base_map.items():
        extra = by_base.get(base)
        if extra:
            result[orig] = extra

    return result
