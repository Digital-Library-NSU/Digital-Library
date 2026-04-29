from datetime import date
from pydantic import BaseModel
from typing import Any

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
    pub_date: date | None
    subjects: str | None
    series: str | None
    cover_path: str | None
    authors: str


class UploadBookResponseDto(BaseModel):
    task_id: str
    status: str


class ImportTaskStatusDto(BaseModel):
    task_id: str
    state: str
    result: Any | None = None
    error: str | None = None