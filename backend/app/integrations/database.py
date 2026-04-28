import psycopg2
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import PG_DSN

engine = create_engine(PG_DSN, echo=True)
SessionMaker = sessionmaker(engine)


def get_db_session():
    return SessionMaker()


_pg_conn = None


def get_pg():
    global _pg_conn
    if not PG_DSN:
        raise Exception(500, "PG_DSN is not set")
    if _pg_conn is None or _pg_conn.closed != 0:
        _pg_conn = psycopg2.connect(PG_DSN)
        _pg_conn.autocommit = True
    return _pg_conn

