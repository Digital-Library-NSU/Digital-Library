from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from app.config import PG_DSN
from app.database import get_pg
from app.integrations.elasticsearch import es_get
from app.integrations.embed_model import _HAS_ST, get_encoder
from app.routes import *


app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"],
)

app.include_router(search_router)
app.include_router(books_router)


# ---------- health ----------
@app.get("/health")
def health():
    info = {}
    try:
        info = es_get("")
    except Exception as e:
        raise HTTPException(503, f"ES not reachable: {e}")
    pg_ok = None
    if PG_DSN:
        try:
            conn = get_pg()
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
            pg_ok = True
        except Exception:
            pg_ok = False
    enc_ok = None
    try:
        if _HAS_ST:
            enc, dim, dev = get_encoder()
            enc_ok = {"ok": True, "dim": dim, "device": dev}
        else:
            enc_ok = {"ok": False,
                      "reason": "sentence-transformers not installed"}
    except Exception as e:
        enc_ok = {"ok": False, "reason": str(e)}
    return {"ok": True, "es": info.get("version", {}), "pg_ok": pg_ok, "encoder": enc_ok}
