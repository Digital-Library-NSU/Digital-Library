from fastapi.routing import APIRouter
from app.config import BOOKS_CONTENT_DIR
from app.dtos.reader_dtos import GetChaptersResponse, ChapterDto
from app.integrations.database import get_db_session
from app.integrations.orm import EditionChapter, Edition
from fastapi import HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import select
from pathlib import Path


router = APIRouter(prefix="/reader")


@router.get("/{book_id}/chapters")
def get_chapters(book_id: int) -> GetChaptersResponse:
    with get_db_session() as db_session:
        edition_id = db_session.execute(select(Edition.id).where(
            Edition.book_id == book_id)).scalar_one_or_none()

        if edition_id is None:
            raise HTTPException(404, "Not found!")

        stmt = select(EditionChapter.id, EditionChapter.title).where(
            EditionChapter.edition_id == edition_id).order_by(EditionChapter.ord)

        result = db_session.execute(stmt).all()

        chapters = [ChapterDto(chapter_id=chapter_id, title=title)
                    for chapter_id, title in result]

        if chapters[0].title.lower() == "cover":
            chapters = chapters[1:]

        return GetChaptersResponse(chapters=chapters)


@router.get("/{book_id}/{chapter_id}")
def get_chapter(book_id: int, chapter_id: int) -> FileResponse:
    return FileResponse(path=Path(BOOKS_CONTENT_DIR + f"/{book_id}/{chapter_id}.xml"), media_type="application/xhtml+xml")
