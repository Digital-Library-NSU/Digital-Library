
from pydantic import BaseModel


class ChapterDto(BaseModel):
    chapter_id: int
    title: str


class GetChaptersResponse(BaseModel):
    chapters: list[ChapterDto]
