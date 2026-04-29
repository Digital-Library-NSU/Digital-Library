from datetime import datetime
from fastapi import Request, HTTPException
from http.cookies import SimpleCookie
from app.integrations.database import get_db_session
from app.integrations.orm import Session
from uuid import UUID


def get_user_id(request: Request) -> UUID:
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
            raise HTTPException(401, "Invalid session id!")

        if (datetime.now() - session.created_time).days > 7:
            db_session.delete(session)
            db_session.commit()
            raise HTTPException(401, "Session expired")

        return session.user_id
