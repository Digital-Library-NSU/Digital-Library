import sys
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse, unquote

import psycopg2

BACKEND_DIR = Path(__file__).resolve().parents[2]
SCHEMA_PATH = BACKEND_DIR / "schema.sql"


def load_schema_sql() -> str:
    try:
        return SCHEMA_PATH.read_text(encoding="utf-8")
    except OSError as e:
        raise RuntimeError(f"Не удалось прочитать schema.sql ({SCHEMA_PATH}): {e}")


SCHEMA_SQL = load_schema_sql()

def parse_dsn_dbname(dsn: str) -> Optional[str]:
    try:
        p = urlparse(dsn)
        db = unquote(p.path.lstrip("/")) if p.scheme.startswith("postgres") else None
        return db or None
    except Exception:
        return None


def connect(dsn: str):
    conn = psycopg2.connect(dsn)
    conn.autocommit = False
    return conn


def ensure_database(dsn: str):
    dbname = parse_dsn_dbname(dsn)
    if not dbname:
        print("[WARN] Не удалось распарсить имя БД из DSN; пропускаю создание.", file=sys.stderr)
        return
    p = urlparse(dsn)
    admin_dsn = dsn.replace(p.path, "/postgres")
    with psycopg2.connect(admin_dsn) as conn:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_database WHERE datname=%s", (dbname,))
            if cur.fetchone():
                return
            print(f"[INFO] Создаю базу {dbname}")
            cur.execute(f'CREATE DATABASE "{dbname}"')


def drop_schema(conn):
    with conn.cursor() as cur:
        cur.execute("""
        DO $$ DECLARE r RECORD;
        BEGIN
          FOR r IN (SELECT schemaname, viewname FROM pg_views WHERE schemaname='public') LOOP
            EXECUTE 'DROP VIEW IF EXISTS '||quote_ident(r.schemaname)||'.'||quote_ident(r.viewname)||' CASCADE';
          END LOOP;
          FOR r IN (SELECT schemaname, tablename FROM pg_tables WHERE schemaname='public') LOOP
            EXECUTE 'DROP TABLE IF EXISTS '||quote_ident(r.schemaname)||'.'||quote_ident(r.tablename)||' CASCADE';
          END LOOP;
        END $$;
        """)
    conn.commit()


def apply_schema(conn, schema_sql: Optional[str] = None):
    sql = schema_sql or SCHEMA_SQL
    with conn.cursor() as cur:
        cur.execute(sql)
    conn.commit()
