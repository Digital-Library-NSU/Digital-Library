from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from app.dtos.read_prog import ReadingProgressDTO, SetReadingProgressDTO
from app.integrations.database import get_db_session
from app.integrations.orm import ContentBlock, t_reading_progress
from app.utils.auth import get_user_id


router = APIRouter(prefix="/read-prog")


@router.post("/")
async def set_reading_progress(request_dto: SetReadingProgressDTO,
                               user_id: Annotated[UUID, Depends(get_user_id)]) -> ReadingProgressDTO:
    if request_dto.block_char_offset < 0:
        raise HTTPException(400, "block_char_offset must be non-negative")

    if not 0 <= request_dto.chapter_scroll_ratio <= 1:
        raise HTTPException(400, "chapter_scroll_ratio must be between 0 and 1")

    async with get_db_session() as db_session:
        row = await db_session.execute(
            select(ContentBlock).where(
                ContentBlock.book_id == request_dto.book_id,
                ContentBlock.chapter_id == request_dto.chapter_id,
                ContentBlock.block_index == request_dto.data_block_index,
            )
        )

        block = row.scalar_one_or_none()
        if block is None:
            raise HTTPException(404, "Content block not found")

        row = await db_session.execute(
            select(func.max(ContentBlock.char_end)).where(
                ContentBlock.book_id == request_dto.book_id,
            )
        )

        total_chars = row.scalar_one_or_none()
        if total_chars is None or total_chars <= 0:
            raise HTTPException(404, "Book content blocks not found")

        block_offset = min(request_dto.block_char_offset, block.char_count)
        absolute_char_pos = min(block.char_start + block_offset, total_chars)

        progress = int((absolute_char_pos / total_chars) * 100)
        progress = max(0, min(progress, 100))

        stmt = insert(t_reading_progress).values(
            user_id=user_id,
            book_id=request_dto.book_id,
            curr_chapter_id=request_dto.chapter_id,
            curr_data_block_index=request_dto.data_block_index,
            curr_block_char_offset=block_offset,
            chapter_scroll_ratio=request_dto.chapter_scroll_ratio,
            progress=progress)
        stmt = stmt.on_conflict_do_update(
            index_elements=['user_id', 'book_id'],
            set_={'curr_chapter_id': request_dto.chapter_id,
                  'curr_data_block_index': request_dto.data_block_index,
                  'curr_block_char_offset': block_offset,
                  'chapter_scroll_ratio': request_dto.chapter_scroll_ratio,
                  'progress': progress})

        await db_session.execute(stmt)
        await db_session.commit()

        return ReadingProgressDTO(book_id=request_dto.book_id,
                                  chapter_id=request_dto.chapter_id,
                                  data_block_index=request_dto.data_block_index,
                                  block_char_offset=block_offset,
                                  chapter_scroll_ratio=request_dto.chapter_scroll_ratio,
                                  progress=progress)


@router.get("/")
async def get_reading_progress(user_id: Annotated[UUID, Depends(
        get_user_id)]) -> list[ReadingProgressDTO]:
    async with get_db_session() as db_session:
        rows = await db_session.execute(select(t_reading_progress).where(
            t_reading_progress.c.user_id == user_id))
        result = rows.fetchall()

        return [ReadingProgressDTO(
            book_id=row[1],
            chapter_id=row[2],
            data_block_index=row[3],
            block_char_offset=row[4],
            chapter_scroll_ratio=row[5],
            progress=row[6]) for row in result]
