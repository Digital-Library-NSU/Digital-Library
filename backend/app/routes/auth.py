from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Request, Response, HTTPException
from sqlalchemy import select
import bcrypt
from uuid import UUID
from http.cookies import SimpleCookie

from app.dtos.auth import AuthDTO
from app.integrations.orm import User, Session
from app.integrations.database import get_db_session


router = APIRouter(prefix='/auth')


def create_session(user_id: UUID, db_session) -> Response:
    new_session = Session()
    new_session.user_id = user_id

    db_session.add(new_session)
    db_session.flush()

    session_id = str(new_session.id)
    db_session.commit()

    res = Response()
    expiration_ts = (datetime.now() + timedelta(days=7)) \
        .astimezone(timezone.utc)
    res.set_cookie(
        'sessionid',
        session_id,
        secure=True,
        httponly=True,
        expires=expiration_ts)
    return res


@router.post('/register')
def register(dto: AuthDTO) -> Response:
    if len(dto.login) > 255:
        raise HTTPException(400, 'Login is too long!')

    hashed_password = bcrypt.hashpw(
        dto.password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    new_user = User()
    new_user.login = dto.login
    new_user.hashed_password = hashed_password

    with get_db_session() as db_session, db_session.begin():
        res = db_session.execute(
            select(User).where(
                User.login == dto.login)).one_or_none()
        if res is not None:
            raise HTTPException(
                409, f'User with this login already exists!')

        db_session.add(new_user)
        db_session.flush()

        return create_session(new_user.id, db_session)


@router.post('/login')
def login(dto: AuthDTO) -> Response:
    if len(dto.login) > 255:
        raise HTTPException(400, 'Login is too long!')

    with get_db_session() as db_session:
        user = db_session.execute(select(User).where(
            User.login == dto.login)).scalar_one_or_none()

        if user is None:
            raise HTTPException(404, 'Can\'t find user!')

        if not bcrypt.checkpw(dto.password.encode('utf-8'),
                              user.hashed_password.encode('utf-8')):
            raise HTTPException(400, 'Invalid password!')

        return create_session(user.id, db_session)


@router.post('/logout')
def logout(request: Request) -> Response:
    cookies_str = request.headers.get("Cookie")
    if cookies_str is None:
        raise HTTPException(401, "Cookies are missing!")

    cookies = SimpleCookie()
    cookies.load(cookies_str)

    if 'sessionid' not in cookies.keys():
        raise HTTPException(401, 'No sessionid in cookies!')

    session_id = UUID(hex=cookies['sessionid'].value)

    with get_db_session() as db_session:
        session = db_session.get(Session, session_id)

        if session is None:
            raise HTTPException(404, 'Session not found!')

        db_session.delete(session)
        db_session.commit()

    res = Response()
    res.set_cookie(
        'sessionid',
        '',
        secure=True,
        httponly=True,
        expires=datetime(1970, 1, 1, tzinfo=timezone.utc))
    return res
