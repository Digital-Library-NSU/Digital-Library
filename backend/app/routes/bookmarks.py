from fastapi import APIRouter, Depends, HTTPException
from app.dtos.bookmarks import UserBookmarksDTO
from utils.auth import get_user_id
from integrations.database import get_db_session
from sqlalchemy import select
from app.integrations.orm import Bookmark
from typing import Annotated
from uuid import UUID

router = APIRouter(prefix="/bookmarks")

@router.get("/{book_id}/{chapter_id}")
async def get_bookmarks(book_id: int, chapter_id: int, user_id: Annotated[UUID, Depends(get_user_id)]) -> UserBookmarksDTO:
    async with get_db_session() as db_session:
        result = await db_session.execute(
            select(User).where(User.id == user_id))
