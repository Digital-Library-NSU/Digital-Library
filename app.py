import os
from typing import Optional, List, Dict, Any

import requests
from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

load_dotenv()

ES_URL = os.getenv("ES_URL", "http://localhost:9200").rstrip("/")
ES_USER = os.getenv("ES_USER") or None
ES_PASS = os.getenv("ES_PASS") or None
IDX_META = os.getenv("ES_INDEX_META", "books_meta")
IDX_CONTENT = os.getenv("ES_INDEX_CONTENT", "books_content")

session = requests.Session()
if ES_USER and ES_PASS:
    session.auth = (ES_USER, ES_PASS)
session.headers.update({"Content-Type": "application/json"})

app = FastAPI(title="Books Search API (ES)")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"],
)

def es_post(path: str, body: Dict[str, Any]) -> Dict[str, Any]:
    r = session.post(f"{ES_URL}/{path.lstrip('/')}", json=body, timeout=30)
    if r.status_code >= 400:
        raise HTTPException(r.status_code, r.text)
    return r.json()

def es_get(path: str) -> Dict[str, Any]:
    r = session.get(f"{ES_URL}/{path}", timeout=15)
    if r.status_code >= 400:
        raise HTTPException(r.status_code, r.text)
    return r.json()

@app.get("/health")
def health():
    try:
        info = es_get("")
    except Exception as e:
        raise HTTPException(503, f"ES not reachable: {e}")
    return {"ok": True, "es": info.get("version", {})}

# ---------- Поиск по метаданным ----------
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
        "_source": True
    }
    res = es_post(f"{IDX_META}/_search", body)
    hits = [
        {"id": h["_source"].get("book_id"), "score": h.get("_score"), **h["_source"]}
        for h in res.get("hits", {}).get("hits", [])
    ]
    return {"total": res.get("hits", {}).get("total", {}).get("value", 0), "hits": hits}

# ---------- Поиск цитат ----------
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

# ---------- Суггест ----------
@app.get("/suggest")
def suggest(prefix: str, field: str = Query("title", pattern="^(title|author)$"), size: int = 5):
    suggest_field = "title_suggest" if field == "title" else "author_suggest"
    body = {
        "suggest": {
            "s1": {"prefix": prefix, "completion": {"field": suggest_field, "size": size}}
        }
    }
    res = es_post(f"{IDX_META}/_search", body)
    options = res.get("suggest", {}).get("s1", [])[0].get("options", []) if res.get("suggest") else []
    return {"suggestions": [o.get("text") for o in options]}
