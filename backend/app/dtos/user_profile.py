from datetime import datetime

from pydantic import BaseModel

from app.dtos.books_dtos import BookCardDto, BookDto


class ProfileReadingBookDto(BaseModel):
    book: BookCardDto
    progress: int
    chapter_id: int


class ProfileReviewDto(BaseModel):
    id: int
    rating: int
    text: str
    created_at: datetime
    updated_at: datetime | None = None
    progress: int | None = None
    chapter_id: int | None = None
    book: BookDto
