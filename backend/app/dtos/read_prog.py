from pydantic import BaseModel


class SetReadingProgressDTO(BaseModel):
    book_id: int
    chapter_id: int
    data_block_index: int
    block_char_offset: int = 0
    chapter_scroll_ratio: float = 0
    is_completed: bool = False


class ReadingProgressDTO(BaseModel):
    book_id: int
    chapter_id: int
    data_block_index: int
    block_char_offset: int
    chapter_scroll_ratio: float
    progress: int  # from 0 to 100
