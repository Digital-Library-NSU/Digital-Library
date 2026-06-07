from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from app.dtos.bookmarks import BookmarkDTO, CreateBookmarkDTO
from app.integrations.database import get_db_session
from app.integrations.orm import Bookmark
from app.utils.auth import get_user_id

router = APIRouter(prefix="/bookmarks")


@router.get("/{book_id}")
async def get_bookmarks(book_id: int,
                        user_id: Annotated[UUID, Depends(get_user_id)]) -> list[BookmarkDTO]:
    async with get_db_session() as db_session:
        res_rows = await db_session.execute(
            select(Bookmark).where(
                Bookmark.owner_id == user_id,
                Bookmark.book_id == book_id))
        user_bookmarks = res_rows.scalars()

        return [BookmarkDTO(
            bookmark_id=bm.id,
            book_id=bm.book_id,
            chapter_id=bm.chapter_id,
            data_block_index=bm.data_block_index
        ) for bm in user_bookmarks]


@router.post("/{book_id}")
async def create_bookmark(request_dto: CreateBookmarkDTO, book_id: int,
                          user_id: Annotated[UUID, Depends(get_user_id)]) -> BookmarkDTO:
    async with get_db_session() as db_session:
        new_bm = Bookmark(
            owner_id=user_id,
            book_id=book_id,
            chapter_id=request_dto.chapter_id,
            data_block_index=request_dto.data_block_index)
        db_session.add(new_bm)
        await db_session.commit()
        return BookmarkDTO(
            bookmark_id=new_bm.id,
            book_id=new_bm.book_id,
            chapter_id=new_bm.book_id,
            data_block_index=new_bm.data_block_index)


@router.delete("/{book_id}/{bookmark_id}")
async def delete_bookmark(book_id: int, bookmark_id: UUID,
                          user_id: Annotated[UUID, Depends(get_user_id)]):
    async with get_db_session() as db_session:
        row = await db_session.execute(
            select(Bookmark).where(
                Bookmark.id == bookmark_id,
                Bookmark.book_id == book_id,
                Bookmark.owner_id == user_id))

        bm = row.scalar_one_or_none()
        if bm is None:
            raise HTTPException(404)

        await db_session.delete(bm)
        await db_session.commit()
