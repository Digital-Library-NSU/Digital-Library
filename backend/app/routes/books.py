from fastapi import APIRouter, HTTPException

from app.dtos.books_dtos import BookCardDto, BookDto
from datetime import datetime
from app.integrations.database import get_db_session
from sqlalchemy import select

from app.models.db.book import Book

router = APIRouter(prefix="/books")


@router.get("/all")
def get_all_books(limit: int | None = None, offset: int = 0) -> list[BookCardDto]:
    with get_db_session() as db_session:
        stmt = select(Book).offset(offset)
        if limit is not None:
            stmt.limit(limit)

        result = []
        for book in db_session.execute(stmt).scalars():
            result.append(
                BookCardDto(
                    book_id=book.id,
                    title=book.title,
                    cover_path=None,
                    authors=", ".join([author.author.name for author in book.book_authors])))

        return result


@router.get("/{book_id}")
def get_book_by_id(book_id: int) -> BookDto:
    with get_db_session() as db_session:
        book = db_session.get(Book, book_id)
        if book is None:
            raise HTTPException(404, "Book not found!")
        return BookDto(
            book_id=book.id,
            title=book.title,
            lang=book.lang,
            description=book.description,
            publisher=book.publisher,
            pub_date=book.pub_date,
            subjects=None if book.subjects is None else ", ".join(
                book.subjects),
            series=book.series,
            cover_path=None,
            authors=", ".join([author.author.name for author in book.book_authors]))
