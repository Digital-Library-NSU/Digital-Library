from contextlib import asynccontextmanager
from typing import AsyncIterator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import PG_DSN


def _to_asyncpg_dsn(dsn: str) -> str:
    if dsn.startswith("postgresql+asyncpg://"):
        return dsn
    if dsn.startswith("postgresql://"):
        return dsn.replace("postgresql://", "postgresql+asyncpg://", 1)
    if dsn.startswith("postgres://"):
        return dsn.replace("postgres://", "postgresql+asyncpg://", 1)
    return dsn


PG_ASYNC_DSN = _to_asyncpg_dsn(PG_DSN) if PG_DSN else ""

async_engine = create_async_engine(PG_ASYNC_DSN, echo=False) if PG_ASYNC_DSN else None

AsyncSessionMaker = (
    async_sessionmaker(async_engine, expire_on_commit=False)
    if async_engine is not None
    else None
)

@asynccontextmanager
async def get_db_session() -> AsyncIterator[AsyncSession]:
    if AsyncSessionMaker is None:
        raise RuntimeError("PG_DSN is not set")

    async with AsyncSessionMaker() as session:
        yield session


async def check_pg_connection() -> bool | None:
    if AsyncSessionMaker is None:
        return None

    try:
        async with get_db_session() as session:
            await session.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


async def close_db_engine() -> None:
    if async_engine is not None:
        await async_engine.dispose()