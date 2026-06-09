from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.dtos.read_prog import ReadingProgressDTO, SetReadingProgressDTO
from app.integrations.database import get_db_session
from app.integrations.orm import Book, Chapter, t_reading_progress
from app.utils.auth import get_user_id


router = APIRouter(prefix="/read-prog")


@router.post("/")
async def set_reading_progress(request_dto: SetReadingProgressDTO,
                               user_id: Annotated[UUID, Depends(get_user_id)]) -> ReadingProgressDTO:
    async with get_db_session() as db_session:
        row = await db_session.execute(
            select(Book.total_blocks_count).where(
                Book.id == request_dto.book_id))

        total_blocks_count = row.scalar_one_or_none()
        if total_blocks_count is None:
            raise HTTPException(404)

        row = await db_session.execute(
            select(Chapter.ord).where(
                Chapter.id == request_dto.chapter_id))

        curr_chapter_ord = row.scalar_one_or_none()
        if curr_chapter_ord is None:
            raise HTTPException(404)

        rows = await db_session.execute(
            select(Chapter.blocks_count).where(
                Chapter.ord < curr_chapter_ord))

        completed_blcks_cnt = sum(rows.scalars().all())  # completed chapters

        progress = int(((completed_blcks_cnt + request_dto.data_block_index + 1)
                       / total_blocks_count) * 100)

        stmt = insert(t_reading_progress).values(
            user_id=user_id,
            book_id=request_dto.book_id,
            curr_chapter_id=request_dto.chapter_id,
            curr_data_block_index=request_dto.data_block_index,
            progress=progress)
        stmt = stmt.on_conflict_do_update(
            index_elements=['user_id', 'book_id'],
            set_={'curr_chapter_id': request_dto.chapter_id,
                  'curr_data_block_index': request_dto.data_block_index,
                  'progress': progress})

        await db_session.execute(stmt)
        await db_session.commit()

        return ReadingProgressDTO(book_id=request_dto.book_id,
                                  chapter_id=request_dto.chapter_id,
                                  data_block_index=request_dto.data_block_index,
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
            progress=row[4]) for row in result]
