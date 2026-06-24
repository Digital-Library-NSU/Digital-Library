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

EMBED_MODEL = os.getenv("EMBED_MODEL", "BAAI/bge-m3")
EMBED_DEVICE = os.getenv("EMBED_DEVICE", "auto")
EMBED_NORMALIZE = (os.getenv("EMBED_NORMALIZE", "true").lower() in {
                   "1", "true", "yes", "on"})
EMBED_ADD_QUERY_PREFIX = (os.getenv(
    "EMBED_ADD_QUERY_PREFIX", "true").lower() in {"1", "true", "yes", "on"})

# MinIO / S3-compatible storage.
MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "http://localhost:9000")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "minioadmin")
MINIO_BUCKET = os.getenv("MINIO_BUCKET", "library-content")
MINIO_REGION = os.getenv("MINIO_REGION", "us-east-1")

# Celery + Redis.
CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0")
CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/1")

# сюда API временно сохраняет загруженные EPUB,
# а Celery worker потом их забирает.
UPLOAD_TMP_DIR = os.getenv("UPLOAD_TMP_DIR", "/tmp/library_uploads")

def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default

    try:
        return int(raw)
    except ValueError:
        return default


MAX_MISSING_SPINE = _int_env("MAX_MISSING_SPINE", 1)

# Email notifications.
SMTP_HOST = os.getenv("SMTP_HOST") or None
SMTP_PORT = _int_env("SMTP_PORT", 587)
SMTP_USER = os.getenv("SMTP_USER") or None
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD") or None
SMTP_FROM = os.getenv("SMTP_FROM", SMTP_USER or "library@example.local")
SMTP_USE_TLS = (os.getenv("SMTP_USE_TLS", "true").lower() in {
                "1", "true", "yes", "on"})
