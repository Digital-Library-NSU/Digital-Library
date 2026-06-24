from datetime import date
from pydantic import BaseModel
from typing import Any

class BookCardDto(BaseModel):
    book_id: int
    title: str
    cover_path: str | None
    authors: str
    avg_rating: float | None
    reviews_count: int


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
    avg_rating: float | None
    reviews_count: int


class UploadBookResponseDto(BaseModel):
    task_id: str
    status: str
    filename: str | None = None


class ImportTaskStatusDto(BaseModel):
    task_id: str
    state: str
    filename: str | None = None
    title: str | None = None
    authors: str | None = None
    stage: str | None = None
    status_label: str | None = None
    progress_percent: float | None = None
    current: int | None = None
    total: int | None = None
    unit: str | None = None
    eta_seconds: int | None = None
    queued: bool = False
    started_at: str | None = None
    updated_at: str | None = None
    result: Any | None = None
    error: str | None = None


class CancelImportResponseDto(BaseModel):
    task_id: str
    state: str
    stage: str
    status_label: str
    filename: str | None = None
