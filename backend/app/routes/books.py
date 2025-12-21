from fastapi import APIRouter, HTTPException, UploadFile, File

from app.dtos.books_dtos import BookCardDto, BookDto
from app.integrations.database import get_db_session
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.integrations.orm import Book, BookAuthor
from app.config import BOOKS_CONTENT_DIR
from pathlib import Path
from app.integrations.database import get_pg
from argparse import Namespace
from app.import_epub import process_epub
from app.config import (
    PG_DSN,
    ES_URL,
    IDX_META,
    IDX_CONTENT,
    EMBED_MODEL,
    EMBED_DEVICE,
    EMBED_NORMALIZE,
    BOOKS_CONTENT_DIR,
)

router = APIRouter(prefix="/books")


def _get_cover_path(book_id: int) -> str | None:
    if not BOOKS_CONTENT_DIR:
        return None

    base_dir = Path(BOOKS_CONTENT_DIR).expanduser() / str(book_id)
    if not base_dir.exists():
        return None

    for ext in (".jpg", ".jpeg", ".png", ".webp"):
        candidate = base_dir / f"cover{ext}"
        if candidate.exists():
            return f"/books_content/{book_id}/cover{ext}"

    return None

@router.get("/all")
def get_all_books(limit: int | None = None, offset: int = 0) -> list[BookCardDto]:
    with get_db_session() as db_session:
        stmt = (
            select(Book)
            .offset(offset)
            .options(selectinload(Book.book_authors).selectinload(BookAuthor.author))
        )
        if limit is not None:
            stmt = stmt.limit(limit)

        result: list[BookCardDto] = []
        for book in db_session.execute(stmt).scalars():
            result.append(
                BookCardDto(
                    book_id=book.id,
                    title=book.title,
                    cover_path=_get_cover_path(book.id),
                    authors=", ".join([ba.author.name for ba in book.book_authors if ba.author]),
                )
            )
        return result


@router.get("/{book_id}")
def get_book_by_id(book_id: int) -> BookDto:
    with get_db_session() as db_session:
        stmt = (
            select(Book)
            .where(Book.id == book_id)
            .options(
                selectinload(Book.book_authors).selectinload(BookAuthor.author)
            )
        )
        book = db_session.execute(stmt).scalars().first()
        if book is None:
            raise HTTPException(404, "Book not found!")
        return BookDto(
            book_id=book.id,
            title=book.title,
            lang=book.lang,
            description=book.description,
            publisher=book.publisher,
            pub_date=book.pub_date,
            subjects=None if book.subjects is None else ", ".join(book.subjects),
            series=book.series,
            cover_path=_get_cover_path(book.id),
            authors=", ".join([ba.author.name for ba in book.book_authors if ba.author]),
        )

@router.post("/upload")
def upload_book(file: UploadFile = File(...)):
    if not file.filename.lower().endswith(".epub"):
        raise HTTPException(status_code=400, detail="Требуется EPUB файл")

    tmp_path = Path("/tmp") / file.filename
    content = file.file.read()
    tmp_path.write_bytes(content)

    export_root_path = Path(BOOKS_CONTENT_DIR).expanduser()
    export_root_path.mkdir(parents=True, exist_ok=True)

    args = Namespace(
        # Postgres
        dsn=PG_DSN,
        root="---",
        create_db=False,
        recreate_schema=False,

        # Elasticsearch
        no_es=False,
        es_url=ES_URL,
        es_index_meta=IDX_META,
        es_index_content=IDX_CONTENT,
        recreate_es=False,
        es_no_source=False,
        es_use_templates=True,
        es_dense_vector_dim=1024,
        es_enable_suggest=False,

        # абзацы/окна
        min_paragraph_words=15,
        no_join_short_paragraphs=False,
        para_window_size=2,
        para_window_stride=1,

        # битые EPUB
        max_missing_spine=50,
        warn_cap=5,

        # эмбеддинги
        embed_model=EMBED_MODEL,
        embed_device=EMBED_DEVICE,
        embed_batch_size=64,
        embed_max_words=256,
        embed_overlap_words=32,
        no_embed_normalize=not EMBED_NORMALIZE,

        # лимит
        limit=0,

        # экспорт
        export_root=BOOKS_CONTENT_DIR,
    )

    try:
        status = process_epub(
            file_path=tmp_path,
            args=args,
        )
        return {"status": status}

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка обработки EPUB: {e}")

    finally:
        if tmp_path.exists():
            tmp_path.unlink()