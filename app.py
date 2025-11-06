import os
from typing import Optional, List, Dict, Any, Tuple

import requests
from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

import psycopg2
from psycopg2.extras import execute_values

# ==== NEW: sentence-transformers для семантики ====
try:
    from sentence_transformers import SentenceTransformer
    _HAS_ST = True
except Exception:
    _HAS_ST = False

load_dotenv()

# --- ES config ---
ES_URL = os.getenv("ES_URL", "http://localhost:9200").rstrip("/")
ES_USER = os.getenv("ES_USER") or None
ES_PASS = os.getenv("ES_PASS") or None
IDX_META = os.getenv("ES_INDEX_META", "books_meta")
IDX_CONTENT = os.getenv("ES_INDEX_CONTENT", "books_content")

# --- PG config (для гидратации карточек) ---
PG_DSN = os.getenv("PG_DSN") or os.getenv("DSN")  # можно прокинуть тот же DSN, что и в импортер
if not PG_DSN:
    PG_DSN = ""

# --- NEW: encoder config ---
EMBED_MODEL = os.getenv("EMBED_MODEL", "BAAI/bge-m3")
EMBED_DEVICE = os.getenv("EMBED_DEVICE", "auto")  # auto|cpu|cuda
EMBED_NORMALIZE = (os.getenv("EMBED_NORMALIZE", "true").lower() in {"1", "true", "yes", "on"})
# Для bge-m3 полезно добавлять префикс "query: " к запросам
EMBED_ADD_QUERY_PREFIX = (os.getenv("EMBED_ADD_QUERY_PREFIX", "true").lower() in {"1", "true", "yes", "on"})

# --- HTTP session for ES ---
session = requests.Session()
if ES_USER and ES_PASS:
    session.auth = (ES_USER, ES_PASS)
session.headers.update({"Content-Type": "application/json"})

app = FastAPI(title="Books Search API (ES + PG hydration + Semantic kNN)")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"],
)

# --- PG connection (ленивая инициализация) ---
_pg_conn = None

def get_pg():
    global _pg_conn
    if not PG_DSN:
        raise HTTPException(500, "PG_DSN is not set")
    if _pg_conn is None or _pg_conn.closed != 0:
        _pg_conn = psycopg2.connect(PG_DSN)
        _pg_conn.autocommit = True
    return _pg_conn

# --- ES helpers ---
def es_post(path: str, body: Dict[str, Any]) -> Dict[str, Any]:
    r = session.post(f"{ES_URL}/{path.lstrip('/')}", json=body, timeout=60)
    if r.status_code >= 400:
        raise HTTPException(r.status_code, r.text)
    return r.json()

def es_get(path: str) -> Dict[str, Any]:
    r = session.get(f"{ES_URL}/{path.lstrip('/')}", timeout=30)
    if r.status_code >= 400:
        raise HTTPException(r.status_code, r.text)
    return r.json()

# --- PG hydration helper ---
def fetch_books_by_ids(ids: List[int]) -> Dict[int, Dict[str, Any]]:
    """
    Возвращает словарь book_id -> карточка книги (из PG), включая список авторов (упорядочен по ord).
    """
    if not ids:
        return {}
    conn = get_pg()
    q = """
      WITH sel AS (
        SELECT UNNEST(%s::bigint[]) AS id
      )
      SELECT
        b.id,
        b.title,
        b.lang,
        b.publisher,
        b.pub_date,
        b.subjects,
        COALESCE(json_agg(a.name ORDER BY ba.ord)
                 FILTER (WHERE a.id IS NOT NULL), '[]') AS author_names,
        b.description
      FROM sel
      JOIN books b ON b.id = sel.id
      LEFT JOIN book_authors ba ON ba.book_id = b.id
      LEFT JOIN authors a ON a.id = ba.author_id
      GROUP BY b.id, b.title, b.lang, b.publisher, b.pub_date, b.subjects, b.description
    """
    with conn.cursor() as cur:
        cur.execute(q, (ids,))
        rows = cur.fetchall()
    by_id: Dict[int, Dict[str, Any]] = {}
    for r in rows:
        by_id[int(r[0])] = {
            "book_id": int(r[0]),
            "title": r[1],
            "lang": r[2],
            "publisher": r[3],
            "pub_year": (int(r[4].year) if r[4] else None),
            "subjects": r[5],
            "author_names": r[6],
            "description": r[7],
        }
    return by_id

# --- NEW: encoder init ---
_encoder: Optional[SentenceTransformer] = None
_encoder_dim: Optional[int] = None

def _pick_device() -> str:
    if EMBED_DEVICE in ("cpu", "cuda"):
        return EMBED_DEVICE
    # auto
    try:
        import torch
        return "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:
        return "cpu"

def get_encoder() -> Tuple[SentenceTransformer, int, str]:
    global _encoder, _encoder_dim
    if not _HAS_ST:
        raise HTTPException(500, "sentence-transformers is not installed")
    if _encoder is None:
        dev = _pick_device()
        enc = SentenceTransformer(EMBED_MODEL, device=dev)
        # Определим размерность
        test_emb = enc.encode(["test"], normalize_embeddings=EMBED_NORMALIZE)
        dim = len(test_emb[0])
        _encoder = enc
        _encoder_dim = dim
        # простая печать в логи
        print(f"[INFO] Semantic encoder ready: model={EMBED_MODEL}, dim={dim}, device={dev}, normalize={EMBED_NORMALIZE}")
    return _encoder, int(_encoder_dim or 0), _encoder._target_device.type  # type: ignore[attr-defined]

def encode_query(text: str) -> List[float]:
    enc, _, _ = get_encoder()
    q = text.strip()
    if EMBED_ADD_QUERY_PREFIX:
        q = f"query: {q}"
    vec = enc.encode([q], normalize_embeddings=EMBED_NORMALIZE)[0]
    return [float(x) for x in vec]

# ---------- health ----------
@app.get("/health")
def health():
    info = {}
    try:
        info = es_get("")
    except Exception as e:
        raise HTTPException(503, f"ES not reachable: {e}")
    # Проверим PG, если настроен
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
    # Проверим encoder
    enc_ok = None
    try:
        if _HAS_ST:
            enc, dim, dev = get_encoder()
            enc_ok = {"ok": True, "dim": dim, "device": dev}
        else:
            enc_ok = {"ok": False, "reason": "sentence-transformers not installed"}
    except Exception as e:
        enc_ok = {"ok": False, "reason": str(e)}
    return {"ok": True, "es": info.get("version", {}), "pg_ok": pg_ok, "encoder": enc_ok}

# ---------- Поиск по метаданным (ES -> hydrate from PG) ----------
@app.get("/books/search")
def search_books(
    q: Optional[str] = Query(None, description="Запрос (название/автор/жанр/описание)"),
    author: Optional[str] = Query(None, description="Фильтр по автору (точное, author_names.raw)"),
    subject: Optional[str] = Query(None, description="Фильтр по жанру/теме (subjects.raw)"),
    lang: Optional[str] = Query(None, description="Фильтр по языку (keyword)"),
    year_from: Optional[int] = Query(None),
    year_to: Optional[int] = Query(None),
    size: int = Query(10, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    must = []
    filters: List[Dict[str, Any]] = []

    if q:
        must.append({
            "multi_match": {
                "query": q,
                "type": "best_fields",
                "fields": [
                    "title^4", "title.ru^4", "title.en^3",
                    "author_names^3", "author_names.ru^3", "author_names.en^2",
                    "subjects^2", "description", "description.ru", "description.en"
                ],
                "operator": "and",
                "fuzziness": "AUTO",
                "prefix_length": 1,
                "fuzzy_transpositions": True
            }
        })

    if author:
        filters.append({"term": {"author_names.raw": author}})
    if subject:
        filters.append({"term": {"subjects.raw": subject}})
    if lang:
        filters.append({"term": {"lang": lang}})
    if year_from or year_to:
        rng = {}
        if year_from is not None: rng["gte"] = year_from
        if year_to   is not None: rng["lte"] = year_to
        filters.append({"range": {"pub_year": rng}})

    body = {
        "from": offset, "size": size,
        "query": {"bool": {"must": must or [{"match_all": {}}], "filter": filters}},
        "_source": ["book_id"]  # берём только идентификатор для гидратации
    }
    res = es_post(f"{IDX_META}/_search", body)

    es_hits = res.get("hits", {}).get("hits", [])
    ids_in_order: List[int] = []
    for h in es_hits:
        src = h.get("_source", {})
        try:
            ids_in_order.append(int(src.get("book_id")))
        except (TypeError, ValueError):
            continue

    by_id = fetch_books_by_ids(ids_in_order)
    hits = []
    for h in es_hits:
        score = h.get("_score")
        bid_raw = h.get("_source", {}).get("book_id")
        try:
            bid = int(bid_raw)
        except (TypeError, ValueError):
            continue
        card = by_id.get(bid)
        if not card:
            continue
        hits.append({"score": score, **card})

    total = res.get("hits", {}).get("total", {}).get("value", 0)
    return {"total": total, "hits": hits}

# ---------- Поиск цитат (BM25 через ES content) ----------
@app.get("/quotes/search")
def search_quotes(
    q: str = Query(..., description="Цитата/фраза для match_phrase"),
    lang_field: Optional[str] = Query(None, description="content | content.ru | content.en"),
    slop: int = Query(2, ge=0, le=10),
    size: int = Query(10, ge=1, le=50),
    offset: int = Query(0, ge=0),
):
    field = lang_field or "content"
    body = {
        "from": offset, "size": size,
        "query": {
            "bool": {
                "should": [
                    {"match_phrase": {field: {"query": q, "slop": slop}}},
                    {"match": {field: {
                        "query": q,
                        "minimum_should_match": "85%",
                        "fuzziness": "AUTO",
                        "prefix_length": 1,
                        "fuzzy_transpositions": True
                    }}}
                ],
                "minimum_should_match": 1
            }
        },
        "highlight": {
            "type": "fvh",
            "fields": { field: {"fragment_size": 180, "number_of_fragments": 1} }
        }
    }
    res = es_post(f"{IDX_CONTENT}/_search", body)
    hits = []
    for h in res.get("hits", {}).get("hits", []):
        src = h.get("_source", {})
        highlight = h.get("highlight", {}).get(field, []) or h.get("highlight", {}).get("content", [])
        hits.append({
            "doc_id": h.get("_id"),
            "score": h.get("_score"),
            "book_id": src.get("book_id"),
            "edition_id": src.get("edition_id"),
            "chapter_ord": src.get("chapter_ord"),
            "chapter_href": src.get("chapter_href"),
            "title": src.get("title"),
            "lang": src.get("lang"),
            "para_start": src.get("para_start"),
            "para_end": src.get("para_end"),
            "window_size": src.get("window_size"),
            "is_heading": src.get("is_heading"),
            "para_type": src.get("para_type"),
            "snippet": highlight[0] if highlight else None
        })
    return {"total": res.get("hits", {}).get("total", {}).get("value", 0), "hits": hits}

# ---------- NEW: Семантический поиск (kNN по content_vec) ----------
@app.get("/semantic/search")
def semantic_search(
    q: str = Query(..., description="Текст запроса (по смыслу)"),
    lang: Optional[str] = Query(None, description="Фильтр языка документа (keyword, например 'ru'|'en')"),
    book_id: Optional[int] = Query(None, description="Фильтр по конкретной книге"),
    size: int = Query(10, ge=1, le=100),
    offset: int = Query(0, ge=0),
    num_candidates: Optional[int] = Query(None, description="kNN кандидатов перед резкой size; по умолчанию size*50, минимум 100"),
):
    """
    Делает:
      1) encode запроса -> вектор
      2) kNN поиск по ES (поле content_vec) в индексе books_content
      3) возвращает параграфы + простые сниппеты и метаданные книги (через PG)
    """
    if not _HAS_ST:
        raise HTTPException(500, "sentence-transformers is not installed on the server")
    try:
        qvec = encode_query(q)
    except Exception as e:
        raise HTTPException(500, f"Encoder error: {e}")

    ncand = max(100, size * 50) if num_candidates is None else max(1, int(num_candidates))
    # Фильтры (после_vector фильтра в ES 8.14 можно класть в 'filter' у knn)
    filters: List[Dict[str, Any]] = []
    if lang:
        filters.append({"term": {"lang": lang}})
    if book_id is not None:
        filters.append({"term": {"book_id": str(book_id)}})

    body = {
        "from": offset,
        "size": size,
        "knn": {
            "field": "content_vec",
            "query_vector": qvec,
            "k": size + offset,           # итоговое 'k' с учётом сдвига
            "num_candidates": ncand,
            **({"filter": {"bool": {"filter": filters}}} if filters else {})
        },
        "_source": [
            "book_id", "edition_id", "chapter_ord", "chapter_href",
            "title", "lang", "para_start", "para_end", "window_size",
            "is_heading", "para_type", "content"
        ]
    }

    res = es_post(f"{IDX_CONTENT}/_search", body)
    hits_raw = res.get("hits", {}).get("hits", [])
    # Собираем book_ids для гидратации
    book_ids: List[int] = []
    for h in hits_raw:
        src = h.get("_source", {})
        try:
            book_ids.append(int(src.get("book_id")))
        except Exception:
            pass
    book_meta = fetch_books_by_ids(list({i for i in book_ids if isinstance(i, int)}))

    def _make_snippet(txt: Optional[str]) -> Optional[str]:
        if not txt:
            return None
        t = txt.strip()
        if len(t) <= 220:
            return t
        return t[:200].rstrip() + "…"

    hits = []
    for h in hits_raw:
        src = h.get("_source", {})
        try:
            bid = int(src.get("book_id"))
        except Exception:
            bid = None
        card = book_meta.get(bid) if bid is not None else None

        # cosine score (ES отдаёт _score ~ cosine sim при normalized vec)
        score = h.get("_score")

        hits.append({
            "doc_id": h.get("_id"),
            "score": score,
            "book_id": src.get("book_id"),
            "edition_id": src.get("edition_id"),
            "chapter_ord": src.get("chapter_ord"),
            "chapter_href": src.get("chapter_href"),
            "title": card["title"] if card else src.get("title"),
            "lang": src.get("lang"),
            "para_start": src.get("para_start"),
            "para_end": src.get("para_end"),
            "window_size": src.get("window_size"),
            "is_heading": src.get("is_heading"),
            "para_type": src.get("para_type"),
            "snippet": _make_snippet(src.get("content")),
            # добавим краткую карточку книги (гидратация)
            "book_card": card if card else None
        })

    total = res.get("hits", {}).get("total", {}).get("value", len(hits))
    return {"total": total, "hits": hits}
