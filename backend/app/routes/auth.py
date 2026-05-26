import asyncio
from datetime import datetime, timedelta, timezone
from http.cookies import SimpleCookie
from uuid import UUID

import bcrypt
from fastapi import APIRouter, HTTPException, Request, Response
from sqlalchemy import select

from app.dtos.auth import AuthDTO
from app.integrations.database import get_db_session
from app.integrations.orm import Session, User

router = APIRouter(prefix="/auth")


def _get_session_id_from_request(request: Request) -> UUID:
    cookies_str = request.headers.get("Cookie")
    if cookies_str is None:
        raise HTTPException(401, "Cookies are missing!")

    cookies = SimpleCookie()
    cookies.load(cookies_str)

    if "sessionid" not in cookies:
        raise HTTPException(401, "No sessionid in cookies!")

    try:
        return UUID(cookies["sessionid"].value)
    except ValueError:
        raise HTTPException(401, "Invalid session id format!")


def _hash_password_sync(password: str) -> str:
    return bcrypt.hashpw(
        password.encode("utf-8"),
        bcrypt.gensalt(),
    ).decode("utf-8")


def _check_password_sync(password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(
        password.encode("utf-8"),
        hashed_password.encode("utf-8"),
    )


def _make_session_response(session_id: str) -> Response:
    res = Response()

    expiration_ts = (datetime.now() + timedelta(days=7)).astimezone(timezone.utc)

    res.set_cookie(
        'sessionid',
        session_id,
        secure=False,
        httponly=True,
        expires=expiration_ts,
    )

    return res


async def create_session(user_id: UUID, db_session) -> Response:
    new_session = Session()
    new_session.user_id = user_id

    db_session.add(new_session)

    await db_session.flush()

    session_id = str(new_session.id)

    await db_session.commit()

    return _make_session_response(session_id)


async def get_current_user(request: Request) -> User:
    session_id = _get_session_id_from_request(request)

    async with get_db_session() as db_session:
        session = await db_session.get(Session, session_id)

        if session is None:
            raise HTTPException(401, "Invalid session!")

        user = await db_session.get(User, session.user_id)

        if user is None:
            raise HTTPException(401, "User not found!")

        return user


@router.post("/register")
async def register(dto: AuthDTO) -> Response:
    if len(dto.login) > 255:
        raise HTTPException(400, "Login is too long!")

    hashed_password = await asyncio.to_thread(_hash_password_sync, dto.password)

    new_user = User()
    new_user.login = dto.login
    new_user.hashed_password = hashed_password

    async with get_db_session() as db_session:
        result = await db_session.execute(
            select(User).where(User.login == dto.login)
        )
        existing_user = result.scalar_one_or_none()

        if existing_user is not None:
            raise HTTPException(409, "User with this login already exists!")

        db_session.add(new_user)

        await db_session.flush()

        return await create_session(new_user.id, db_session)


@router.post("/login")
async def login(dto: AuthDTO) -> Response:
    if len(dto.login) > 255:
        raise HTTPException(400, "Login is too long!")

    async with get_db_session() as db_session:
        result = await db_session.execute(
            select(User).where(User.login == dto.login)
        )
        user = result.scalar_one_or_none()

        if user is None:
            raise HTTPException(404, "Can't find user!")

        password_ok = await asyncio.to_thread(
            _check_password_sync,
            dto.password,
            user.hashed_password,
        )

        if not password_ok:
            raise HTTPException(400, "Invalid password!")

        return await create_session(user.id, db_session)


@router.post("/logout")
async def logout(request: Request) -> Response:
    session_id = _get_session_id_from_request(request)

    async with get_db_session() as db_session:
        session = await db_session.get(Session, session_id)

        if session is None:
            raise HTTPException(404, "Session not found!")

        await db_session.delete(session)
        await db_session.commit()

    res = Response()

    res.set_cookie(
        "sessionid",
        "",
        secure=False,
        httponly=True,
        expires=datetime(1970, 1, 1, tzinfo=timezone.utc),
    )

    return res