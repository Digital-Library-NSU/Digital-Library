import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.integrations.database import check_pg_connection, close_db_engine
from app.integrations.elasticsearch import close_es_client, es_get
from app.integrations.embed_model import _HAS_ST, get_encoder
from app.routes import *



@asynccontextmanager
async def lifespan(app: FastAPI):
    yield

    await asyncio.gather(
        close_es_client(),
        close_db_engine(),
    )


app = FastAPI(lifespan=lifespan)


app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:4200"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(search_router)
app.include_router(books_router)
app.include_router(reader_router)
app.include_router(auth_router)
app.include_router(user_router)
app.include_router(review_router)
app.include_router(bookmarks_router)


def _check_encoder_sync():
    try:
        if _HAS_ST:
            enc, dim, dev = get_encoder()
            return {"ok": True, "dim": dim, "device": dev}

        return {"ok": False, "reason": "sentence-transformers not installed"}

    except Exception as e:
        return {"ok": False, "reason": str(e)}


@app.get("/health")
async def health():
    try:
        info = await es_get("")
    except Exception as e:
        raise HTTPException(503, f"ES not reachable: {e}")

    pg_ok, enc_ok = await asyncio.gather(
        check_pg_connection(),
        asyncio.to_thread(_check_encoder_sync),
    )

    return {
        "ok": True,
        "es": info.get("version", {}),
        "pg_ok": pg_ok,
        "encoder": enc_ok,
    }
