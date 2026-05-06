import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import psycopg2
import zipfile
from bs4 import BeautifulSoup

import torch
from sentence_transformers import SentenceTransformer

from app.integrations.object_storage import (
    book_cover_key,
    chapter_key,
    cover_content_type,
    put_bytes_sync,
)

from .text_utils import (
    html_to_indexed_blocks,
    coalesce_short_paragraphs,
    paragraph_windows,
    build_window_content_and_offsets,
    tokenize_words,
)
from .epub_parse import parse_container_and_opf, parse_opf
from .es_support import ensure_es_indices, es_bulk_safe

_ENCODER_CACHE: Dict[Tuple[str, str], Tuple[SentenceTransformer, Optional[int], str]] = {}
_ES_DIM_ENSURED: Dict[Tuple[str, str, str, int], bool] = {}

# ---------- Embedding helpers ----------

def _resolve_device(device_mode: str) -> str:
    if device_mode == "auto":
        if torch is not None and torch.cuda.is_available():
            return "cuda"
        if torch is not None and getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
            return "mps"
        return "cpu"
    if device_mode in ("cpu", "cuda", "mps"):
        return device_mode
    return "cpu"


def get_encoder(model_name: Optional[str], device_mode: str = "auto"):
    if not model_name:
        return None, "cpu"
    if SentenceTransformer is None:
        raise RuntimeError("sentence-transformers не установлен. pip install sentence-transformers")

    dev = _resolve_device(device_mode)
    key = (model_name, dev)

    cached = _ENCODER_CACHE.get(key)
    if cached is not None:
        enc, _dim, _dev = cached
        return enc, _dev

    enc = SentenceTransformer(model_name, device=dev)
    enc.eval()

    if torch is not None and dev == "cuda":
        try:
            torch.backends.cuda.matmul.allow_tf32 = True
        except Exception:
            pass
        try:
            torch.backends.cudnn.allow_tf32 = True
        except Exception:
            pass
        if hasattr(torch, "set_float32_matmul_precision"):
            try:
                torch.set_float32_matmul_precision("high")
            except Exception:
                pass

    print(f"[INFO] Embedding model loaded: {model_name}, device={dev}")

    _ENCODER_CACHE[key] = (enc, None, dev)
    return enc, dev


def get_encoder_dim(model_name: str, device: str) -> int:
    key = (model_name, device)
    cached = _ENCODER_CACHE.get(key)
    if cached is None:
        enc = SentenceTransformer(model_name, device=device)
        enc.eval()
        _ENCODER_CACHE[key] = (enc, None, device)
        cached = _ENCODER_CACHE[key]

    enc, dim, dev = cached
    if dim is not None:
        return dim

    try:
        dim = enc.get_sentence_embedding_dimension()
    except Exception:
        test = enc.encode(["test"], normalize_embeddings=False)
        dim = len(test[0])

    _ENCODER_CACHE[key] = (enc, int(dim), dev)
    print(f"[INFO] Embedding model dim resolved: {model_name}, dim={dim}, device={dev}")
    return int(dim)


def parse_date(date_raw: str) -> Optional[str]:
    if not date_raw:
        return None
    fmts = ["%Y-%m-%d", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S", "%Y-%m", "%Y"]
    for fmt in fmts:
        try:
            dt = datetime.strptime(date_raw[: len(fmt)], fmt)
            return dt.date().isoformat()
        except Exception:
            continue
    return None


def find_or_insert_book(cur, meta, subjects_list: List[str]) -> int:
    authors = meta.get("creators") or None
    pub_date = parse_date(meta.get("date_raw") or "")

    cur.execute(
        """
        SELECT id FROM books
        WHERE title = %s
          AND authors IS NOT DISTINCT FROM %s
          AND lang IS NOT DISTINCT FROM %s
          AND publisher IS NOT DISTINCT FROM %s
          AND pub_date IS NOT DISTINCT FROM %s
        ORDER BY id
        LIMIT 1
        """,
        (
            meta.get("title"),
            authors,
            meta.get("language"),
            meta.get("publisher"),
            pub_date,
        ),
    )
    row = cur.fetchone()
    if row:
        return row[0]

    cur.execute(
        """
        INSERT INTO books (title, authors, lang, description, publisher, pub_date, subjects, series)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
        RETURNING id
        """,
        (
            meta.get("title"),
            authors,
            meta.get("language"),
            meta.get("description"),
            meta.get("publisher"),
            pub_date,
            subjects_list if subjects_list else None,
            None,
        ),
    )
    return cur.fetchone()[0]


def insert_chapter(cur, book_id: int, ord_: int, title: Optional[str]) -> int:
    cur.execute(
        """
        INSERT INTO chapters (book_id, ord, title)
        VALUES (%s,%s,%s)
        ON CONFLICT (book_id, ord) DO UPDATE
        SET title = COALESCE(EXCLUDED.title, chapters.title)
        RETURNING id
        """,
        (book_id, ord_, title or None),
    )
    return cur.fetchone()[0]


def insert_paragraph_meta(
    cur,
    book_id: int,
    chapter_id: Optional[int],
    block_start: int,
    block_end: int,
    tokens_from: int,
    tokens_to: int,
    es_doc_id: str,
    lang: Optional[str],
    para_type: Optional[str],
):
    cur.execute(
        """
        INSERT INTO content_paragraphs
          (book_id, chapter_id, block_start, block_end,
           tokens_from, tokens_to, es_doc_id, lang, para_type)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT (es_doc_id) DO NOTHING
        """,
        (
            book_id,
            chapter_id,
            block_start,
            block_end,
            tokens_from,
            tokens_to,
            es_doc_id,
            lang,
            para_type,
        ),
    )


def _fallback_book_title(file_path: Path, meta_title: Optional[str]) -> str:
    if meta_title and meta_title.strip():
        return meta_title
    return Path(file_path).stem

def _read_zip_resource(z: zipfile.ZipFile, meta: Dict, href: str) -> tuple[bytes, str]:
    try:
        return z.read(href), href
    except KeyError:
        opf_dir = Path(meta.get("opf_path") or "").parent
        alt = str(opf_dir / href) if str(opf_dir) not in ("", ".") else href
        return z.read(alt), alt

def _preflight_check_spine_missing(z: zipfile.ZipFile, meta: Dict, args, file_name: str) -> bool:
    missing = 0
    max_warn = getattr(args, "warn_cap", 5)
    max_missing_spine = getattr(args, "max_missing_spine", 50)

    opf_dir = Path(meta.get("opf_path") or "").parent

    for href, media_type in meta.get("spine") or []:
        if not href or not href.lower().endswith((".xhtml", ".html", ".htm")):
            continue
        try:
            z.getinfo(href)
            continue
        except KeyError:
            pass

        alt = str(opf_dir / href) if str(opf_dir) not in ("", ".") else href
        if alt != href:
            try:
                z.getinfo(alt)
                continue
            except KeyError:
                pass

        missing += 1
        if missing <= max_warn:
            print(f"[WARN] missing spine resource {href}", file=sys.stderr)

        if missing > max_missing_spine:
            print(
                f"[WARN] too many missing spine resources ({missing}) → skip WHOLE book (no Postgres, no ES) for {file_name}",
                file=sys.stderr,
            )
            return False

    if missing > 0:
        print(f"[WARN] missing spine resources total: {missing} (file: {file_name})", file=sys.stderr)

    return True



def _connect_from_args(args):
    dsn = getattr(args, "dsn", None)
    if not dsn:
        raise RuntimeError("args.dsn is required to connect to Postgres")
    return psycopg2.connect(dsn)


def _upload_cover_to_storage(z: zipfile.ZipFile, meta: Dict, book_id: int) -> None:
    cover_href = meta.get("cover_href")

    if not cover_href:
        return

    try:
        cover_bytes, resolved_href = _read_zip_resource(z, meta, cover_href)
    except KeyError:
        print(f"[WARN] cover image not found in ZIP: {cover_href}", file=sys.stderr)
        return

    ext = Path(resolved_href).suffix or ".jpg"

    put_bytes_sync(
        key=book_cover_key(book_id, ext),
        data=cover_bytes,
        content_type=cover_content_type(ext),
    )


def _upload_chapter_to_storage(book_id: int, chapter_id: int, html: str) -> None:
    _blocks, annotated_html = html_to_indexed_blocks(html)

    put_bytes_sync(
        key=chapter_key(book_id, chapter_id),
        data=annotated_html.encode("utf-8"),
        content_type="application/xhtml+xml; charset=utf-8",
    )

def process_epub(file_path: Path, args):
    conn = _connect_from_args(args)

    try:
        idx_meta: str = args.es_index_meta
        idx_content: str = args.es_index_content

        print(f"[INFO] Processing EPUB: {file_path.name}")

        with zipfile.ZipFile(file_path, "r") as z:
            # 1) OPF
            try:
                opf_path = parse_container_and_opf(z)
                meta = parse_opf(z, opf_path)
            except Exception as e:
                print(f"[WARN] {file_path.name}: OPF parse failed: {e}", file=sys.stderr)
                return "skipped"

            if not _preflight_check_spine_missing(z, meta, args, file_path.name):
                return "skipped"

            with conn.cursor() as cur:
                # 2) Book
                book_id = find_or_insert_book(cur, meta, meta["subjects"])
                try:
                    _upload_cover_to_storage(z, meta, book_id)
                except Exception as e:
                    print(f"[WARN] cannot upload cover to storage for book {book_id}: {e}", file=sys.stderr)

                # 3) Chapters + upload annotated chapter XML to MinIO
                chapter_ids: List[Optional[int]] = []

                for idx, (href, media_type) in enumerate(meta["spine"], start=1):
                    if not href or not href.lower().endswith((".xhtml", ".html", ".htm")):
                        chapter_ids.append(None)
                        continue

                    try:
                        raw, resolved_href = _read_zip_resource(z, meta, href)
                    except KeyError:
                        chapter_ids.append(None)
                        continue

                    html = raw.decode("utf-8", errors="ignore")

                    chap_title = None
                    try:
                        soup = BeautifulSoup(html, "lxml")
                        h = soup.find(["h1", "h2", "title"])
                        chap_title = (h.get_text() if h else None) if h else None

                        if chap_title:
                            chap_title = chap_title.strip()
                    except Exception:
                        pass

                    cid = insert_chapter(cur, book_id, idx, chap_title)
                    chapter_ids.append(cid)

                    if cid is not None:
                        try:
                            _upload_chapter_to_storage(book_id, cid, html)
                        except Exception as e:
                            print(f"[WARN] cannot upload chapter {cid} xml to storage: {e}", file=sys.stderr)

                # 4) ES meta document
                book_title_for_es = _fallback_book_title(file_path, meta.get("title"))

                if not args.no_es:
                    authors = meta["creators"]
                    pub_year = None
                    pd = parse_date(meta["date_raw"])

                    if pd:
                        try:
                            pub_year = int(pd[:4])
                        except Exception:
                            pub_year = None

                    meta_doc = {
                        "book_id": str(book_id),
                        "title": book_title_for_es,
                        "author_names": authors or [],
                        "subjects": meta["subjects"] or [],
                        "publisher": meta["publisher"] or "",
                        "lang": meta["language"] or "",
                        "pub_year": pub_year,
                        "description": meta["description"] or "",
                    }
                else:
                    meta_doc = {}

                # 5) ES content documents + Postgres paragraph metadata
                content_docs: List[Dict] = []
                texts_for_embed: List[str] = []
                words_running = 0

                missing = 0
                max_warn = getattr(args, "warn_cap", 5)

                for c_idx, (href, media_type) in enumerate(meta["spine"], start=1):
                    if not href or not href.lower().endswith((".xhtml", ".html", ".htm")):
                        continue

                    try:
                        raw, resolved_href = _read_zip_resource(z, meta, href)
                    except KeyError:
                        missing += 1

                        if missing <= max_warn:
                            print(f"[WARN] missing spine resource {href}", file=sys.stderr)

                        continue

                    html = raw.decode("utf-8", errors="ignore")
                    chapter_id = chapter_ids[c_idx - 1] if c_idx - 1 < len(chapter_ids) else None

                    blocks, _annotated_html = html_to_indexed_blocks(html)

                    if not args.no_join_short_paragraphs:
                        blocks = coalesce_short_paragraphs(blocks, args.min_paragraph_words)

                    block_token_counts = [len(tokenize_words(block.text)) for block in blocks]

                    prefix = [0]
                    for c in block_token_counts:
                        prefix.append(prefix[-1] + c)

                    wins = paragraph_windows(
                        blocks,
                        args.para_window_size,
                        args.para_window_stride,
                    )

                    base_offset = words_running

                    for win_idx, (start, end, win_blocks) in enumerate(wins):
                        para_text, block_offsets = build_window_content_and_offsets(win_blocks)

                        if not para_text.strip():
                            continue

                        kind_first = win_blocks[0].kind if win_blocks else "paragraph"

                        block_start = win_blocks[0].block_start
                        block_end = win_blocks[-1].block_end

                        w_from = base_offset + prefix[start]
                        w_to = base_offset + prefix[end + 1]

                        base_doc_id = f"{book_id}:{c_idx}:{win_idx}"

                        content_docs.append(
                            {
                                "_id": base_doc_id,
                                "book_id": str(book_id),

                                "chapter_id": chapter_id,
                                "chapter_ord": c_idx,

                                "lang": meta["language"] or "",
                                "title": book_title_for_es,
                                "content": para_text,
                                "length": len(para_text),

                                "block_start": block_start,
                                "block_end": block_end,
                                "block_offsets": block_offsets,

                                "para_type": kind_first,
                                "subchunk_idx": 0,
                            }
                        )

                        if args.embed_model:
                            texts_for_embed.append(para_text)

                        insert_paragraph_meta(
                            cur,
                            book_id,
                            chapter_id,
                            block_start,
                            block_end,
                            w_from,
                            w_to,
                            base_doc_id,
                            meta["language"] or None,
                            para_type=kind_first,
                        )

                    words_running += prefix[-1]

                if missing > 0:
                    print(
                        f"[WARN] missing spine resources total (content phase): {missing} (file: {file_path.name})",
                        file=sys.stderr,
                    )

                # 6) Embeddings
                if args.embed_model:
                    enc, enc_dev = get_encoder(args.embed_model, device_mode=args.embed_device)

                    if args.es_dense_vector_dim <= 0:
                        enc_dim = get_encoder_dim(args.embed_model, enc_dev)
                        ensure_key = (args.es_url, idx_meta, idx_content, int(enc_dim))

                        if not _ES_DIM_ENSURED.get(ensure_key):
                            ensure_es_indices(
                                args.es_url,
                                idx_meta,
                                idx_content,
                                store_source=not args.es_no_source,
                                use_templates=args.es_use_templates,
                                dense_vec_dim=enc_dim,
                                enable_suggest=args.es_enable_suggest,
                            )
                            _ES_DIM_ENSURED[ensure_key] = True

                    batch = args.embed_batch_size
                    vecs: List[List[float]] = []

                    if torch is not None and hasattr(torch, "inference_mode"):
                        ctx = torch.inference_mode
                    else:
                        ctx = torch.no_grad

                    with ctx():
                        for i in range(0, len(texts_for_embed), batch):
                            chunk = texts_for_embed[i: i + batch]
                            embs = enc.encode(
                                chunk,
                                normalize_embeddings=not args.no_embed_normalize,
                                convert_to_numpy=True,
                            )
                            vecs.extend(embs.tolist())

                    vi = 0
                    for d in content_docs:
                        d["content_vec"] = vecs[vi]
                        vi += 1

                # 7) Commit Postgres + bulk ES
                conn.commit()

                if not args.no_es:
                    es_bulk_safe(
                        args.es_url,
                        idx_meta,
                        idx_content,
                        meta_doc,
                        content_docs,
                    )

                conn.commit()

                return {
                    "status": "ok",
                    "book_id": book_id,
                    "title": book_title_for_es,
                    "chapters": len([cid for cid in chapter_ids if cid is not None]),
                    "content_docs": len(content_docs),
                }

    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass

        raise

    finally:
        try:
            conn.close()
        except Exception:
            pass