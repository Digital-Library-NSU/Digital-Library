#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_library_db.py — EPUB -> PostgreSQL (метаданные) + Elasticsearch (текст по абзацам).
ТЕКСТ книг в Postgres НЕ хранится. Текст только в ES.

Изменение: в индекс контента ES поле "title" теперь ВСЕГДА берётся из dc:title OPF
(метаданные книги). Заголовки глав НЕ подставляются в это поле.
"""

import argparse
import hashlib
import json
import re
import sys
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import unquote, urlparse

import psycopg2
import requests
from bs4 import BeautifulSoup
from tqdm import tqdm
import unicodedata

# ---------------- helpers ----------------

WORD_RE = re.compile(r"[^\W\d_]+", re.UNICODE)

SCHEMA_SQL = """
-- === базовая схема Postgres (БЕЗ текста книг) ===

CREATE TABLE IF NOT EXISTS authors (
  id        BIGSERIAL PRIMARY KEY,
  name      TEXT NOT NULL UNIQUE,
  sort_name TEXT
);

CREATE TABLE IF NOT EXISTS books (
  id          BIGSERIAL PRIMARY KEY,
  title       TEXT NOT NULL,
  sort_title  TEXT,
  lang        TEXT,
  description TEXT,
  publisher   TEXT,
  pub_date    DATE,
  subjects    TEXT[],
  series      TEXT,
  meta        JSONB
);

CREATE TABLE IF NOT EXISTS book_authors (
  book_id   BIGINT REFERENCES books(id) ON DELETE CASCADE,
  author_id BIGINT REFERENCES authors(id) ON DELETE CASCADE,
  role      TEXT,
  ord       INT,
  PRIMARY KEY (book_id, author_id)
);

CREATE TABLE IF NOT EXISTS book_identifiers (
  book_id BIGINT REFERENCES books(id) ON DELETE CASCADE,
  scheme  TEXT NOT NULL,
  value   TEXT NOT NULL,
  PRIMARY KEY (book_id, scheme, value),
  UNIQUE (scheme, value)
);

CREATE TABLE IF NOT EXISTS editions (
  id          BIGSERIAL PRIMARY KEY,
  book_id     BIGINT REFERENCES books(id) ON DELETE CASCADE,
  format      TEXT NOT NULL,
  storage_key TEXT NOT NULL,   -- путь к файлу EPUB
  size_bytes  BIGINT,
  sha256      TEXT UNIQUE,
  drm         BOOLEAN,
  opf_path    TEXT,
  created_at  TIMESTAMPTZ DEFAULT now()
);

-- Оглавление/главы (без текста)
CREATE TABLE IF NOT EXISTS edition_chapters (
  id          BIGSERIAL PRIMARY KEY,
  edition_id  BIGINT REFERENCES editions(id) ON DELETE CASCADE,
  ord         INT NOT NULL,
  title       TEXT,
  href        TEXT
);

-- Метаданные АБЗАЦЕВ/окон (без текста)
CREATE TABLE IF NOT EXISTS content_paragraphs (
  id           BIGSERIAL PRIMARY KEY,
  book_id      BIGINT REFERENCES books(id) ON DELETE CASCADE,
  edition_id   BIGINT REFERENCES editions(id) ON DELETE CASCADE,
  chapter_id   BIGINT REFERENCES edition_chapters(id) ON DELETE SET NULL,
  para_start   INT NOT NULL,      -- номер первого абзаца окна (0-based)
  para_end     INT NOT NULL,      -- номер последнего абзаца окна (включительно)
  window_size  INT NOT NULL,
  tokens_from  INT,               -- границы по словным токенам в рамках книги/издания
  tokens_to    INT,
  es_index     TEXT,
  es_doc_id    TEXT UNIQUE,
  lang         TEXT,
  embedding    TEXT,              -- позже можно заменить на VECTOR(N) при включении pgvector
  para_type    TEXT,              -- тип первого абзаца в окне: paragraph|heading|list|blockquote|pre
  is_heading   BOOLEAN
);

CREATE INDEX IF NOT EXISTS idx_books_title ON books USING GIN (to_tsvector('simple', coalesce(title,'')));
CREATE INDEX IF NOT EXISTS idx_books_subjects ON books USING GIN (subjects);
CREATE INDEX IF NOT EXISTS idx_editions_book ON editions (book_id);
CREATE INDEX IF NOT EXISTS idx_chapters_ed ON edition_chapters (edition_id, ord);
CREATE INDEX IF NOT EXISTS idx_paragraphs_book_start ON content_paragraphs (book_id, para_start);
"""

def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def norm_space(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()

def strip_accents_lower(s: str) -> str:
    s = unicodedata.normalize("NFKC", s)
    return s.lower()

def html_to_text(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    for bad in soup(["script", "style"]):
        bad.decompose()
    text = soup.get_text(separator=" ").replace("\xa0", " ")
    return norm_space(text)

def tokenize_words(text: str) -> List[str]:
    text = strip_accents_lower(text)
    return WORD_RE.findall(text)

def html_to_paragraph_blocks(html: str) -> List[Tuple[str, str]]:
    """
    Возвращает [(para_type, text), ...] в порядке документа.
    para_type: 'heading'|'paragraph'|'list'|'blockquote'|'pre'
    """
    soup = BeautifulSoup(html, "lxml")
    for bad in soup(["script", "style", "nav", "aside", "footer", "header"]):
        bad.decompose()
    for br in soup.find_all("br"):
        br.replace_with("\n")

    blocks: List[Tuple[str, str]] = []
    tags = ["h1","h2","h3","h4","h5","h6","p","li","blockquote","pre","code"]
    for el in soup.find_all(tags, recursive=True):
        txt = norm_space(el.get_text(" ").replace("\xa0", " "))
        if not txt:
            continue
        t = el.name.lower()
        if t in {"h1","h2","h3","h4","h5","h6"}:
            kind = "heading"
        elif t == "li":
            kind = "list"
        elif t == "blockquote":
            kind = "blockquote"
        elif t in {"pre","code"}:
            kind = "pre"
        else:
            kind = "paragraph"
        blocks.append((kind, txt))

    if not blocks:
        text = html_to_text(html)
        paras = [norm_space(p) for p in re.split(r"\n{2,}", text) if norm_space(p)]
        blocks = [("paragraph", p) for p in paras]

    return blocks

def coalesce_short_paragraphs(blocks: List[Tuple[str,str]], min_words: int) -> List[Tuple[str,str]]:
    """Склеивает подряд идущие короткие не-заголовочные абзацы до минимума."""
    out: List[Tuple[str,str]] = []
    buf_type, buf_txt, buf_w = None, "", 0

    def flush():
        nonlocal buf_type, buf_txt, buf_w
        if buf_txt:
            out.append((buf_type or "paragraph", norm_space(buf_txt)))
        buf_type, buf_txt, buf_w = None, "", 0

    for kind, txt in blocks:
        w = len(tokenize_words(txt))
        if buf_w == 0:
            buf_type, buf_txt, buf_w = kind, txt, w
            continue
        if buf_w < min_words and kind != "heading":
            buf_txt = f"{buf_txt}\n\n{txt}"
            buf_w += w
        else:
            flush()
            buf_type, buf_txt, buf_w = kind, txt, w
    flush()
    return out

def paragraph_windows(blocks: List[Tuple[str,str]], window_size: int, stride: int):
    """
    blocks: список (kind, text) после возможной склейки коротышей.
    Возвращает [(start, end, [(kind,text), ...]), ...]
    """
    window_size = max(1, int(window_size))
    stride = max(1, int(stride))
    n = len(blocks)
    if n == 0:
        return []
    if window_size == 1:
        return [(i, i, [blocks[i]]) for i in range(0, n, stride)]
    out = []
    i = 0
    last = n - window_size
    while i <= last:
        out.append((i, i + window_size - 1, blocks[i:i + window_size]))
        i += stride
    return out

# ---------------- DB ops ----------------

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
    """Создать целевую БД, если не существует (через 'postgres')."""
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

def apply_schema(conn):
    with conn.cursor() as cur:
        cur.execute(SCHEMA_SQL)
    conn.commit()

def enable_pgvector(conn, vector_dim: int):
    prev = conn.autocommit
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            try:
                cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
            except Exception as e:
                print(f"[WARN] EXT vector: {e}", file=sys.stderr)
    finally:
        conn.autocommit = prev

    with conn.cursor() as cur:
        cur.execute("""
            DO $$
            BEGIN
              IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name='content_paragraphs' AND column_name='embedding' AND data_type='text'
              ) THEN
                ALTER TABLE content_paragraphs DROP COLUMN embedding;
                ALTER TABLE content_paragraphs ADD COLUMN embedding VECTOR(%s);
              END IF;
            END$$;
        """, (int(vector_dim),))
    conn.commit()

def insert_paragraph_meta(cur, book_id: int, edition_id: int, chapter_id: Optional[int],
                          para_start: int, para_end: int, window_size: int,
                          tokens_from: int, tokens_to: int,
                          es_index: str, es_doc_id: str, lang: Optional[str],
                          para_type: Optional[str], is_heading: Optional[bool]):
    cur.execute("""
        INSERT INTO content_paragraphs
          (book_id, edition_id, chapter_id, para_start, para_end, window_size,
           tokens_from, tokens_to, es_index, es_doc_id, lang, para_type, is_heading)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT (es_doc_id) DO NOTHING
    """, (book_id, edition_id, chapter_id, para_start, para_end, window_size,
          tokens_from, tokens_to, es_index, es_doc_id, lang, para_type, is_heading))

# ---------------- ES ----------------

def es_request(method: str, url: str, json_body=None, timeout=30):
    r = requests.request(method, url, json=json_body, timeout=timeout)
    if r.status_code >= 400:
        raise RuntimeError(f"ES {method} {url} failed: {r.status_code} {r.text[:500]}")
    return r.json() if r.text else {}

def ensure_es_indices(es_url: str, idx_meta: str, idx_content: str,
                      store_source: bool = True,
                      use_templates: bool = True,
                      dense_vec_dim: int = 0,
                      enable_suggest: bool = False):
    analysis = {
        "char_filter": {
            "punct_strip": {"type": "pattern_replace",
                            "pattern": r"[\p{Punct}\p{S}]+", "replacement": " "}
        },
        "filter": {
            "russian_stop":    {"type": "stop",    "stopwords": "_russian_"},
            "russian_stemmer": {"type": "stemmer", "language": "russian"},
            "english_stop":    {"type": "stop",    "stopwords": "_english_"},
            "english_stemmer": {"type": "stemmer", "language": "english"}
        },
        "normalizer": {
            "kw_lower": {"type": "custom", "filter": ["lowercase"]}
        },
        "analyzer": {
            "quote": {"type": "custom", "char_filter": ["html_strip", "punct_strip"],
                      "tokenizer": "standard", "filter": ["lowercase"]},
            "ru":    {"type": "custom", "tokenizer": "standard",
                      "filter": ["lowercase", "russian_stop", "russian_stemmer"]},
            "en":    {"type": "custom", "tokenizer": "standard",
                      "filter": ["lowercase", "english_stop", "english_stemmer"]}
        }
    }

    def meta_mappings():
        base = {
            "dynamic": "false",
            "properties": {
                "book_id":     {"type": "keyword", "normalizer": "kw_lower"},
                "title": {
                    "type": "text", "analyzer": "quote",
                    "fields": {
                        "raw": {"type": "keyword", "normalizer": "kw_lower"},
                        "ru":  {"type": "text", "analyzer": "ru"},
                        "en":  {"type": "text", "analyzer": "en"}
                    }
                },
                "author_names": {
                    "type": "text", "analyzer": "quote",
                    "fields": {
                        "raw": {"type": "keyword", "normalizer": "kw_lower"},
                        "ru":  {"type": "text", "analyzer": "ru"},
                        "en":  {"type": "text", "analyzer": "en"}
                    }
                },
                "subjects": {
                    "type": "text", "analyzer": "quote",
                    "fields": {"raw": {"type": "keyword", "normalizer": "kw_lower"}}
                },
                "publisher": {
                    "type": "text", "analyzer": "quote",
                    "fields": {"raw": {"type": "keyword", "normalizer": "kw_lower"}}
                },
                "lang":     {"type": "keyword", "normalizer": "kw_lower"},
                "pub_year": {"type": "integer"},
                "description": {
                    "type": "text", "analyzer": "quote",
                    "fields": {
                        "ru": {"type": "text", "analyzer": "ru"},
                        "en": {"type": "text", "analyzer": "en"}
                    }
                }
            }
        }
        if enable_suggest:
            base["properties"]["title_suggest"]  = {"type": "completion", "analyzer": "quote"}
            base["properties"]["author_suggest"] = {"type": "completion", "analyzer": "quote"}
        return base

    def content_mappings():
        props = {
            "book_id":     {"type": "keyword", "normalizer": "kw_lower"},
            "edition_id":  {"type": "keyword", "normalizer": "kw_lower"},
            "chapter_ord": {"type": "integer"},
            "chapter_href":{"type": "keyword"},
            "lang":        {"type": "keyword", "normalizer": "kw_lower"},
            "title": {
                "type": "text", "analyzer": "quote",
                "fields": {
                    "raw": {"type": "keyword", "normalizer": "kw_lower"},
                    "ru":  {"type": "text", "analyzer": "ru"},
                    "en":  {"type": "text", "analyzer": "en"}
                }
            },
            "content": {
                "type": "text", "analyzer": "quote",
                "term_vector": "with_positions_offsets",
                "fields": {
                    "ru": {"type": "text", "analyzer": "ru"},
                    "en": {"type": "text", "analyzer": "en"}
                }
            },
            "length":      {"type": "integer"},
            "para_start":  {"type": "integer"},
            "para_end":    {"type": "integer"},
            "window_size": {"type": "integer"},
            "is_heading":  {"type": "boolean"},
            "para_type":   {"type": "keyword"}
        }
        if dense_vec_dim and dense_vec_dim > 0:
            props["content_vec"] = {
                "type": "dense_vector", "dims": dense_vec_dim,
                "index": True, "similarity": "cosine"
            }
        return {"_source": {"enabled": store_source}, "dynamic": "false", "properties": props}

    if use_templates:
        tmpl_meta = {
            "index_patterns": ["books_meta*"],
            "template": {"settings": {"analysis": analysis}, "mappings": meta_mappings()},
            "priority": 10
        }
        tmpl_content = {
            "index_patterns": ["books_content*"],
            "template": {"settings": {"analysis": analysis}, "mappings": content_mappings()},
            "priority": 10
        }
        es_request("PUT", f"{es_url}/_index_template/books_meta_template", tmpl_meta)
        es_request("PUT", f"{es_url}/_index_template/books_content_template", tmpl_content)

    for name, mappings in [(idx_meta, meta_mappings()), (idx_content, content_mappings())]:
        r = requests.get(f"{es_url}/{name}", timeout=15)
        if r.status_code == 404:
            body = {"settings": {"analysis": analysis}, "mappings": mappings}
            es_request("PUT", f"{es_url}/{name}", body)
        elif r.status_code >= 400:
            raise RuntimeError(f"ES check index {name} failed: {r.status_code} {r.text[:500]}")

def es_bulk(es_url: str, index: str, docs: List[Dict], id_field: Optional[str] = None, chunk_size: int = 2000):
    import gzip
    def gen_actions(batch):
        lines = []
        for d in batch:
            if id_field and id_field in d:
                _id = d[id_field]
                src = {k: v for k, v in d.items() if k != id_field}
                meta = {"index": {"_index": index, "_id": _id}}
            else:
                src = d
                meta = {"index": {"_index": index}}
            lines.append(json.dumps(meta, ensure_ascii=False))
            lines.append(json.dumps(src, ensure_ascii=False))
        return ("\n".join(lines) + "\n").encode("utf-8")
    for i in range(0, len(docs), chunk_size):
        batch = docs[i:i + chunk_size]
        data = gen_actions(batch)
        headers = {"Content-Type": "application/x-ndjson", "Content-Encoding": "gzip"}
        r = requests.post(f"{es_url}/_bulk", data=gzip.compress(data), headers=headers, timeout=120)
        if r.status_code >= 400 or '"errors":true' in r.text:
            raise RuntimeError(f"ES bulk failed: {r.status_code} {r.text[:1000]}")

# ---------------- EPUB -> DB+ES ----------------

def parse_container_and_opf(z: zipfile.ZipFile) -> str:
    container_xml = z.read("META-INF/container.xml")
    import xml.etree.ElementTree as ET
    root = ET.fromstring(container_xml)
    ns = {"c": "urn:oasis:names:tc:opendocument:xmlns:container"}
    rf = root.find(".//c:rootfile", ns)
    if rf is None:
        raise RuntimeError("rootfile not found in container.xml")
    return rf.attrib.get("full-path", "")

def parse_opf(z: zipfile.ZipFile, opf_path: str):
    import xml.etree.ElementTree as ET
    opf_xml = z.read(opf_path)
    opf = ET.fromstring(opf_xml)
    ns = {"dc": "http://purl.org/dc/elements/1.1/",
          "opf": "http://www.idpf.org/2007/opf"}

    # Берём ПЕРВЫЙ непустой dc:title (иногда их несколько)
    titles = [norm_space(el.text) for el in opf.findall(".//dc:title", ns) if el is not None and norm_space(el.text)]
    title = titles[0] if titles else None

    def get_text(path):
        el = opf.find(path, ns)
        return norm_space(el.text) if el is not None and el.text else ""

    language = (get_text(".//dc:language") or None)
    publisher = get_text(".//dc:publisher") or None
    date_raw = get_text(".//dc:date") or ""
    description = get_text(".//dc:description") or None
    creators = [norm_space(el.text) for el in opf.findall(".//dc:creator", ns) if el is not None and norm_space(el.text)]
    subjects = [norm_space(s.text) for s in opf.findall(".//dc:subject", ns) if s is not None and norm_space(s.text)]
    identifiers = []
    for ide in opf.findall(".//dc:identifier", ns):
        txt = norm_space(ide.text) if ide is not None and ide.text else ""
        if txt:
            scheme = ide.attrib.get("{http://www.idpf.org/2007/opf}scheme", "") or ""
            identifiers.append(((scheme.upper() or "ID"), txt))

    mf_items = {}
    base = str(Path(opf_path).parent)
    for it in opf.findall(".//{http://www.idpf.org/2007/opf}item"):
        it_id = it.attrib.get("id")
        href = it.attrib.get("href")
        media_type = it.attrib.get("media-type")
        if it_id and href:
            href_path = str(Path(base) / href) if base not in ("", ".") else href
            mf_items[it_id] = (href_path, media_type)

    spine = []
    for itref in opf.findall(".//{http://www.idpf.org/2007/opf}itemref"):
        ref = itref.attrib.get("idref")
        if ref and ref in mf_items:
            spine.append(mf_items[ref])

    return {
        "title": title, "creators": creators, "language": language, "publisher": publisher,
        "date_raw": date_raw, "description": description, "subjects": subjects,
        "identifiers": identifiers, "opf_path": opf_path, "manifest": mf_items, "spine": spine
    }

def parse_date(date_raw: str) -> Optional[str]:
    if not date_raw:
        return None
    fmts = ["%Y-%m-%d", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S", "%Y-%m", "%Y"]
    for fmt in fmts:
        try:
            dt = datetime.strptime(date_raw[:len(fmt)], fmt)
            return dt.date().isoformat()
        except Exception:
            continue
    return None

def upsert_author(cur, name: str) -> int:
    cur.execute(
        "INSERT INTO authors (name) VALUES (%s) "
        "ON CONFLICT (name) DO UPDATE SET name=EXCLUDED.name "
        "RETURNING id",
        (name,),
    )
    return cur.fetchone()[0]

def find_or_insert_book(cur, meta, subjects_list: List[str]) -> int:
    for scheme, value in meta["identifiers"]:
        cur.execute("SELECT book_id FROM book_identifiers WHERE scheme=%s AND value=%s", (scheme, value))
        row = cur.fetchone()
        if row:
            return row[0]
    cur.execute(
        """
        INSERT INTO books (title, sort_title, lang, description, publisher, pub_date, subjects, series, meta)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
        RETURNING id
        """,
        (
            meta["title"], meta["title"], meta["language"], meta["description"], meta["publisher"],
            parse_date(meta["date_raw"]), subjects_list if subjects_list else None, None,
            json.dumps({"identifiers": meta["identifiers"], "opf_path": meta["opf_path"]}, ensure_ascii=False),
        ),
    )
    book_id = cur.fetchone()[0]
    for i, raw in enumerate(meta["creators"]):
        aid = upsert_author(cur, raw)
        cur.execute(
            "INSERT INTO book_authors (book_id, author_id, role, ord) VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING",
            (book_id, aid, "author", i),
        )
    for scheme, value in meta["identifiers"]:
        cur.execute(
            "INSERT INTO book_identifiers (book_id, scheme, value) VALUES (%s,%s,%s) ON CONFLICT DO NOTHING",
            (book_id, scheme, value),
        )
    return book_id

def insert_or_get_edition(cur, book_id: int, storage_key: str, size_bytes: int, sha256: str, opf_path: str) -> Optional[int]:
    cur.execute("SELECT id FROM editions WHERE sha256=%s", (sha256,))
    row = cur.fetchone()
    if row:
        return row[0]
    cur.execute(
        """
        INSERT INTO editions (book_id, format, storage_key, size_bytes, sha256, drm, opf_path)
        VALUES (%s,'EPUB',%s,%s,%s,false,%s) RETURNING id
        """,
        (book_id, storage_key, size_bytes, sha256, opf_path),
    )
    return cur.fetchone()[0]

def insert_chapter(cur, edition_id: int, ord_: int, title: Optional[str], href: str) -> int:
    cur.execute(
        """
        INSERT INTO edition_chapters (edition_id, ord, title, href)
        VALUES (%s,%s,%s,%s) RETURNING id
        """,
        (edition_id, ord_, title or None, href),
    )
    return cur.fetchone()[0]

def es_bulk_safe(es_url: str, idx_meta: str, idx_content: str, meta_doc: Dict, content_docs: List[Dict]):
    # meta
    if meta_doc:
        try:
            es_bulk(es_url, idx_meta, [meta_doc], id_field="book_id", chunk_size=1)
        except Exception as e:
            print(f"[WARN] ES meta bulk failed for book {meta_doc.get('book_id')}: {e}", file=sys.stderr)
    # content
    if content_docs:
        try:
            es_bulk(es_url, idx_content, content_docs, id_field="_id", chunk_size=1000)
        except Exception as e:
            print(f"[WARN] ES content bulk failed: {e}", file=sys.stderr)

def _fallback_book_title(file_path: Path, meta_title: Optional[str]) -> str:
    """Тихий запасной вариант, если в OPF нет dc:title."""
    if meta_title and meta_title.strip():
        return meta_title
    # как крайняя мера — имя файла без расширения
    return Path(file_path).stem

def process_epub(conn, file_path: Path, args, es_url: Optional[str], idx_meta: str, idx_content: str):
    size_bytes = file_path.stat().st_size
    sha = sha256_file(file_path)

    with zipfile.ZipFile(file_path, "r") as z, conn.cursor() as cur:
        # 1) OPF
        try:
            opf_path = parse_container_and_opf(z)
            meta = parse_opf(z, opf_path)
        except Exception as e:
            print(f"[WARN] {file_path.name}: OPF parse failed: {e}", file=sys.stderr)
            return

        # 2) книга + издание
        book_id = find_or_insert_book(cur, meta, meta["subjects"])
        edition_id = insert_or_get_edition(cur, book_id, str(file_path), size_bytes, sha, meta["opf_path"])
        if not edition_id:
            conn.commit()
            return

        # 3) главы (href/title/ord), без текста
        chapter_ids: List[Optional[int]] = []
        for idx, (href, media_type) in enumerate(meta["spine"], start=1):
            if not href or not href.lower().endswith((".xhtml", ".html", ".htm")):
                chapter_ids.append(None)
                continue
            chap_title = None
            try:
                raw = z.read(href)
            except KeyError:
                alt = str(Path(Path(meta["opf_path"]).parent) / href)
                try:
                    raw = z.read(alt); href = alt
                except KeyError:
                    print(f"[WARN] missing spine resource {href}", file=sys.stderr)
                    chapter_ids.append(None); continue
            try:
                html = raw.decode("utf-8", errors="ignore")
                soup = BeautifulSoup(html, "lxml")
                h = soup.find(["h1", "h2", "title"])
                chap_title = norm_space(h.get_text()) if h else None
            except Exception:
                pass
            cid = insert_chapter(cur, edition_id, idx, chap_title, href)
            chapter_ids.append(cid)

        # 4) ES: метадок книги
        book_title_for_es = _fallback_book_title(file_path, meta.get("title"))
        if not args.no_es:
            authors = meta["creators"]
            pub_year = None
            pd = parse_date(meta["date_raw"])
            if pd:
                try:
                    pub_year = int(pd[:4])
                except:
                    pub_year = None
            meta_doc = {
                "book_id": str(book_id),
                "title": book_title_for_es,
                "author_names": authors or [],
                "subjects": meta["subjects"] or [],
                "publisher": meta["publisher"] or "",
                "lang": meta["language"] or "",
                "pub_year": pub_year,
                "description": meta["description"] or ""
            }
        else:
            meta_doc = {}

        # 5) ES: контент абзацами/окнами
        content_docs: List[Dict] = []
        words_running = 0  # глобальный счётчик слов по книге/изданию

        for c_idx, (href, media_type) in enumerate(meta["spine"], start=1):
            if not href or not href.lower().endswith((".xhtml", ".html", ".htm")):
                continue
            try:
                raw = z.read(href)
            except KeyError:
                alt = str(Path(Path(meta["opf_path"]).parent) / href)
                try:
                    raw = z.read(alt); href = alt
                except KeyError:
                    print(f"[WARN] missing spine resource {href}", file=sys.stderr)
                    continue

            html = raw.decode("utf-8", errors="ignore")
            chapter_id = chapter_ids[c_idx - 1]

            blocks = html_to_paragraph_blocks(html)
            if args.join_short_paragraphs:
                blocks = coalesce_short_paragraphs(blocks, args.min_paragraph_words)

            # токены по абзацам и префиксные суммы внутри главы
            para_token_counts = [len(tokenize_words(txt)) for kind, txt in blocks]
            prefix = [0]
            for c in para_token_counts:
                prefix.append(prefix[-1] + c)

            wins = paragraph_windows(blocks, args.para_window_size, args.para_window_stride)

            base_offset = words_running
            for (start, end, win_blocks) in wins:
                win_texts = [t for _, t in win_blocks]
                win_kinds = [k for k, _ in win_blocks]
                para_text = "\n\n".join(win_texts)
                if not para_text.strip():
                    continue

                is_head = any(k == "heading" for k in win_kinds)
                kind_first = win_kinds[0] if win_kinds else "paragraph"

                w_from = base_offset + prefix[start]
                w_to   = base_offset + prefix[end + 1]

                doc_id = f"{edition_id}:{c_idx}:{start}"

                # ВАЖНО: title = ТОЛЬКО НАЗВАНИЕ КНИГИ ИЗ OPF
                content_docs.append({
                    "_id": doc_id,
                    "book_id": str(book_id),
                    "edition_id": str(edition_id),
                    "chapter_ord": c_idx,
                    "chapter_href": href,
                    "lang": meta["language"] or "",
                    "title": book_title_for_es,
                    "content": para_text,
                    "length": len(para_text),
                    "para_start": start,
                    "para_end": end,
                    "window_size": end - start + 1,
                    "is_heading": is_head,
                    "para_type": kind_first
                })

                insert_paragraph_meta(
                    cur, book_id, edition_id, chapter_id,
                    start, end, end - start + 1,
                    w_from, w_to,
                    idx_content, doc_id, meta["language"] or None,
                    para_type=kind_first, is_heading=is_head
                )

            # после главы двигаем глобальный счётчик слов на общее число слов в главе
            words_running += prefix[-1]

        # 6) коммиты + ES bulk
        conn.commit()
        if not args.no_es:
            es_bulk_safe(args.es_url, idx_meta, idx_content, meta_doc, content_docs)
        conn.commit()

def main():
    ap = argparse.ArgumentParser(description="EPUB -> Postgres (meta) + Elasticsearch (paragraphs).")
    ap.add_argument("--dsn", required=True, help="PostgreSQL DSN (e.g., postgresql://user:pass@host:5432/db)")
    ap.add_argument("--root", required=True, help="Root folder with .epub files (recursively)")
    ap.add_argument("--create-db", action="store_true")
    ap.add_argument("--recreate-schema", action="store_true")

    # ES
    ap.add_argument("--no-es", action="store_true")
    ap.add_argument("--es-url", type=str, default="http://localhost:9200")
    ap.add_argument("--es-index-meta", type=str, default="books_meta")
    ap.add_argument("--es-index-content", type=str, default="books_content")
    ap.add_argument("--es-no-source", action="store_true", help="Disable _source in content index")
    ap.add_argument("--es-use-templates", action="store_true", help="Create index templates")
    ap.add_argument("--es-dense-vector-dim", type=int, default=0)
    ap.add_argument("--es-enable-suggest", action="store_true")

    # Абзацы и окна
    ap.add_argument("--min-paragraph-words", type=int, default=15)
    ap.add_argument("--join-short-paragraphs", action="store_true")
    ap.add_argument("--para-window-size", type=int, default=1, help=">=1 (1 = без перекрытий)")
    ap.add_argument("--para-window-stride", type=int, default=1, help=">=1 (1 = максимальное перекрытие)")

    # Векторная готовность (Postgres)
    ap.add_argument("--with-pgvector", action="store_true")
    ap.add_argument("--vector-dim", type=int, default=768)

    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    if args.create_db:
        ensure_database(args.dsn)

    conn = connect(args.dsn)
    try:
        if args.recreate_schema:
            drop_schema(conn)
        apply_schema(conn)
        if args.with_pgvector:  # NOTE: typo fix ниже
            pass
    except Exception:
        pass
    # fix typo из блока выше:
    try:
        if args.with_pgvector:
            enable_pgvector(conn, args.vector_dim)
    except Exception as e:
        print(f"[WARN] pgvector setup: {e}", file=sys.stderr)

    try:
        if not args.no_es:
            ensure_es_indices(
                args.es_url, args.es_index_meta, args.es_index_content,
                store_source=not args.es_no_source,
                use_templates=args.es_use_templates,
                dense_vec_dim=args.es_dense_vector_dim,
                enable_suggest=args.es_enable_suggest
            )

        root = Path(args.root).expanduser()
        files = sorted([p for p in root.rglob("*.epub")])
        if args.limit > 0:
            files = files[: args.limit]
        if not files:
            print("[INFO] EPUB файлы не найдены в указанной папке.", file=sys.stderr)
            return

        for p in tqdm(files, desc="Importing EPUBs"):
            try:
                process_epub(conn, p, args, None if args.no_es else args.es_url, args.es_index_meta, args.es_index_content)
            except Exception as e:
                conn.rollback()
                print(f"[ERROR] {p.name}: {e}", file=sys.stderr)
    finally:
        conn.close()

if __name__ == "__main__":
    main()
