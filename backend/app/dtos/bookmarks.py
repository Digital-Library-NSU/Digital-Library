from uuid import UUID

from pydantic import BaseModel


class BookmarkDTO(BaseModel):
    bookmark_id: UUID
    book_id: int
    chapter_id: int
    data_block_index: int


class CreateBookmarkDTO(BaseModel):
    chapter_id: int
    data_block_index: int
