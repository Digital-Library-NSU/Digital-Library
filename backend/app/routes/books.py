from pathlib import Path
from uuid import uuid4
import asyncio
from celery.result import AsyncResult
from fastapi import APIRouter, HTTPException, UploadFile, File
from fastapi.responses import Response
from sqlalchemy import select

from app.celery_app import celery_app
from app.config import UPLOAD_TMP_DIR
from app.dtos.books_dtos import (
    BookCardDto,
    BookDto,
    UploadBookResponseDto,
    ImportTaskStatusDto,
)
from app.integrations.database import get_db_session
from app.integrations.object_storage import find_cover_key, get_object_bytes
from app.integrations.orm import Book
from app.tasks.import_tasks import import_epub_task

router = APIRouter(prefix="/books")


async def _get_cover_path(book_id: int) -> str | None:
    cover_key = await find_cover_key(book_id)

    if cover_key is None:
        return None

    return f"/books/{book_id}/cover"


@router.get("/all")
async def get_all_books(limit: int | None = None, offset: int = 0) -> list[BookCardDto]:
    async with get_db_session() as db_session:
        stmt = select(Book).offset(offset)

        if limit is not None:
            stmt = stmt.limit(limit)

        result = await db_session.execute(stmt)
        books = list(result.scalars())

    cover_paths = [
        await _get_cover_path(int(book.id))
        for book in books
    ]

    return [
        BookCardDto(
            book_id=book.id,
            title=book.title,
            cover_path=cover_paths[idx],
            authors=", ".join(book.authors or []),
        )
        for idx, book in enumerate(books)
    ]


@router.get("/{book_id}/cover")
async def get_book_cover(book_id: int) -> Response:
    cover_key = await find_cover_key(book_id)

    if cover_key is None:
        raise HTTPException(404, "Cover not found")

    try:
        data, content_type = await get_object_bytes(cover_key)
    except FileNotFoundError:
        raise HTTPException(404, "Cover not found")

    return Response(
        content=data,
        media_type=content_type,
    )


@router.get("/{book_id}")
async def get_book_by_id(book_id: int) -> BookDto:
    async with get_db_session() as db_session:
        stmt = select(Book).where(Book.id == book_id)

        result = await db_session.execute(stmt)
        book = result.scalars().first()

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
        cover_path=await _get_cover_path(book.id),
        authors=", ".join(book.authors or []),
    )


@router.post("/upload", response_model=UploadBookResponseDto, status_code=202)
async def upload_book(file: UploadFile = File(...)) -> UploadBookResponseDto:
    if not file.filename or not file.filename.lower().endswith(".epub"):
        raise HTTPException(status_code=400, detail="Требуется EPUB файл")

    upload_dir = Path(UPLOAD_TMP_DIR)
    upload_dir.mkdir(parents=True, exist_ok=True)

    safe_name = Path(file.filename).name
    tmp_path = upload_dir / f"{uuid4()}_{safe_name}"

    content = await file.read()
    tmp_path.write_bytes(content)

    task = import_epub_task.delay(
        str(tmp_path),
        safe_name,
    )

    return UploadBookResponseDto(
        task_id=task.id,
        status="queued",
    )


def _get_import_status_sync(task_id: str) -> ImportTaskStatusDto:
    task = AsyncResult(task_id, app=celery_app)

    error = str(task.result) if task.failed() else None

    result = None
    if task.successful():
        result = task.result
    elif isinstance(task.info, dict):
        result = task.info

    return ImportTaskStatusDto(
        task_id=task_id,
        state=task.state,
        result=result,
        error=error,
    )


@router.get("/imports/{task_id}", response_model=ImportTaskStatusDto)
async def get_import_status(task_id: str) -> ImportTaskStatusDto:
    return await asyncio.to_thread(_get_import_status_sync, task_id)