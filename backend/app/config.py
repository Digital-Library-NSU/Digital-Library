import os

from dotenv import load_dotenv

load_dotenv()

ES_URL = os.getenv("ES_URL", "http://localhost:9200").rstrip("/")
ES_USER = os.getenv("ES_USER") or None
ES_PASS = os.getenv("ES_PASS") or None
IDX_META = os.getenv("ES_INDEX_META", "books_meta")
IDX_CONTENT = os.getenv("ES_INDEX_CONTENT", "books_content")

PG_DSN = os.getenv("PG_DSN") or os.getenv("DSN")
if not PG_DSN:
    PG_DSN = ""

print("PG DSN: ", PG_DSN)

EMBED_MODEL = os.getenv("EMBED_MODEL", "BAAI/bge-m3")
EMBED_DEVICE = os.getenv("EMBED_DEVICE", "auto")
EMBED_NORMALIZE = (os.getenv("EMBED_NORMALIZE", "true").lower() in {
                   "1", "true", "yes", "on"})
EMBED_ADD_QUERY_PREFIX = (os.getenv(
    "EMBED_ADD_QUERY_PREFIX", "true").lower() in {"1", "true", "yes", "on"})

BOOKS_CONTENT_DIR = os.getenv("BOOKS_CONTENT_DIR", "books_content")
