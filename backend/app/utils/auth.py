from datetime import datetime
from http.cookies import SimpleCookie
from uuid import UUID

from fastapi import HTTPException, Request

from app.integrations.database import get_db_session
from app.integrations.orm import Session


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


async def get_user_id(request: Request) -> UUID:
    session_id = _get_session_id_from_request(request)

    async with get_db_session() as db_session:
        session = await db_session.get(Session, session_id)

        if session is None:
            raise HTTPException(401, "Invalid session id!")

        if (datetime.now() - session.created_time).days > 7:
            await db_session.delete(session)
            await db_session.commit()
            raise HTTPException(401, "Session expired")

        return session.user_id