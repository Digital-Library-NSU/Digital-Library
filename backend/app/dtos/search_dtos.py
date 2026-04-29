from typing import Optional, List

from pydantic import BaseModel

from app.dtos.books_dtos import BookCardDto


class SnippetDTO(BaseModel):
    doc_id: str
    chapter_id: Optional[int] = None
    chapter_ord: int
    chapter_path: str
    chapter_title: Optional[str] = None
    snippet: str

    block_start: Optional[int] = None
    block_end: Optional[int] = None

    hit_block_index: Optional[int] = None


class FullTextHitDTO(BaseModel):
    book: BookCardDto
    score: float
    match_type: str  # "meta" | "quote"
    snippet: Optional[SnippetDTO] = None


class FullTextResponseDTO(BaseModel):
    total: int
    hits: List[FullTextHitDTO]


class SemanticHitDTO(BaseModel):
    book: BookCardDto
    score: float
    snippet: SnippetDTO


class SemanticResponseDTO(BaseModel):
    total: int
    hits: List[SemanticHitDTO]
