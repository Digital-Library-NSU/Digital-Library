from pydantic import BaseModel
from typing import List, Optional
from app.dtos.search_dtos import SnippetDTO

class ChapterDto(BaseModel):
    chapter_id: int
    title: Optional[str] = None


class GetChaptersResponse(BaseModel):
    chapters: list[ChapterDto]

class InBookSearchHitDTO(BaseModel):
    score: float
    snippet: SnippetDTO


class InBookSearchResponseDTO(BaseModel):
    total: int
    hits: List[InBookSearchHitDTO]