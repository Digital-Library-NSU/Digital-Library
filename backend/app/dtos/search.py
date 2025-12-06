from typing import List, Optional, Literal
from pydantic import BaseModel


class BookCardDTO(BaseModel):
    id: int
    title: str
    lang: Optional[str] = None
    publisher: Optional[str] = None
    pub_year: Optional[int] = None
    subjects: Optional[List[str]] = None
    author_names: List[str]
    description: Optional[str] = None


class SnippetDTO(BaseModel):
    doc_id: str
    edition_id: str
    chapter_ord: int
    chapter_href: str
    snippet: str


class FullTextHitDTO(BaseModel):
    book: BookCardDTO
    score: float
    match_type: Literal["meta", "quote"]
    snippet: Optional[SnippetDTO] = None


class FullTextResponseDTO(BaseModel):
    total: int
    hits: List[FullTextHitDTO]


class SemanticHitDTO(BaseModel):
    book: BookCardDTO
    score: float
    snippet: SnippetDTO


class SemanticResponseDTO(BaseModel):
    total: int
    hits: List[SemanticHitDTO]