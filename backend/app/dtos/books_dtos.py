from datetime import datetime
from pydantic import BaseModel


class BookCardDto(BaseModel):
    book_id: int
    title: str
    cover_path: str | None
    authors: str


class BookDto(BaseModel):
    book_id: int
    title: str
    lang: str | None
    description: str | None
    publisher: str | None
    pub_date: datetime | None
    subjects: str | None
    series: str | None
    cover_path: str | None
    authors: str