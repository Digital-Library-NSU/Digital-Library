from pydantic import BaseModel


class SetReadingProgressDTO(BaseModel):
    book_id: int
    chapter_id: int
    data_block_index: int


class ReadingProgressDTO(BaseModel):
    book_id: int
    chapter_id: int
    data_block_index: int
    progress: int  # from 0 to 100
