from typing import Annotated
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from app.dtos.user import UserInfoDTO
from app.integrations.database import get_db_session
from app.integrations.orm import User
from app.utils.auth import get_user_id


router = APIRouter(prefix='/user')


@router.get('/info')
def get_info(user_id: Annotated[UUID, Depends(get_user_id)]) -> UserInfoDTO:
    with get_db_session() as db_session:
        user = db_session.execute(select(User).where(
            User.id == user_id)).scalar_one_or_none()

        if user is None:
            raise HTTPException(404, 'User not found!')

        return UserInfoDTO(login=user.login, role=user.role)
