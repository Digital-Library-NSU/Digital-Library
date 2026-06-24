import sys
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import psycopg2
import numpy as np
import torch
from bs4 import BeautifulSoup
from sentence_transformers import SentenceTransformer

from app.integrations.object_storage import (book_cover_key, chapter_key,
                                             cover_content_type,
                                             put_bytes_sync)

from .covers import normalize_zip_path, resolve_href_relative, zip_actual_name
from .epub_parse import parse_container_and_opf, parse_opf
from .es_support import ensure_es_indices, es_bulk_atomic, es_delete_book_docs
from .text_utils import (build_window_content_and_offsets,
                         coalesce_short_paragraphs, html_to_indexed_blocks,
                         paragraph_windows, tokenize_words)

_ENCODER_CACHE: Dict[Tuple[str, str],
                     Tuple[SentenceTransformer, Optional[int], str]] = {}
_ES_DIM_ENSURED: Dict[Tuple[str, str, str, int], bool] = {}


def book_vector_from_window_embeddings(
    embeddings: "np.ndarray",
    step: int = 2,
) -> Optional[List[float]]:
    if embeddings.size == 0:
        return None

    selected = embeddings[:: max(1, step)]
    if selected.size == 0:
        return None

    book_vec = selected.mean(axis=0)
    norm = np.linalg.norm(book_vec)

    if norm <= 0:
        return None

    return (book_vec / norm).astype(float).tolist()

# ---------- Embedding helpers ----------


def _resolve_device(device_mode: str) -> str:
    if device_mode == "auto":
        if torch is not None and torch.cuda.is_available():
            return "cuda"
        if torch is not None and getattr(
                torch.backends, "mps", None) and torch.backends.mps.is_available():
            return "mps"
        return "cpu"
    if device_mode in ("cpu", "cuda", "mps"):
        return device_mode
    return "cpu"


def get_encoder(model_name: Optional[str], device_mode: str = "auto"):
    if not model_name:
        return None, "cpu"
    if SentenceTransformer is None:
        raise RuntimeError(
            "sentence-transformers не установлен. pip install sentence-transformers")

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


def is_encoder_cached(model_name: Optional[str], device_mode: str = "auto") -> bool:
    if not model_name:
        return False

    dev = _resolve_device(device_mode)
    return (model_name, dev) in _ENCODER_CACHE


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
    print(
        f"[INFO] Embedding model dim resolved: {model_name}, dim={dim}, device={dev}")
    return int(dim)


def clear_encoder_cache() -> None:
    _ENCODER_CACHE.clear()

    if torch is not None and torch.cuda.is_available():
        try:
            torch.cuda.empty_cache()
        except Exception:
            pass


def parse_date(date_raw: str) -> Optional[str]:
    if not date_raw:
        return None
    fmts = [
        "%Y-%m-%d",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m",
        "%Y"]
    for fmt in fmts:
        try:
            dt = datetime.strptime(date_raw[: len(fmt)], fmt)
            return dt.date().isoformat()
        except Exception:
            continue
    return None


def find_or_insert_book(
        cur, meta, subjects_list: List[str], total_blocks_count: int) -> int:
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
        INSERT INTO books (title, authors, lang, description, publisher, pub_date, subjects, series, total_blocks_count)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
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
            total_blocks_count
        ),
    )
    return cur.fetchone()[0]


def insert_chapter(cur, book_id: int, ord_: int,
                   title: Optional[str], blocks_count: int) -> int:
    cur.execute(
        """
        INSERT INTO chapters (book_id, ord, title, blocks_count)
        VALUES (%s,%s,%s,%s)
        ON CONFLICT (book_id, ord) DO UPDATE
        SET title = COALESCE(EXCLUDED.title, chapters.title),
            blocks_count = COALESCE(EXCLUDED.blocks_count, chapters.blocks_count)
        RETURNING id
        """,
        (book_id, ord_, title or None, blocks_count),
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


def delete_book_blocks(cur, book_id: int) -> None:
    cur.execute(
        "DELETE FROM content_blocks WHERE book_id = %s",
        (book_id,),
    )


def insert_content_block(
    cur,
    book_id: int,
    chapter_id: int,
    block_index: int,
    char_start: int,
    char_end: int,
    char_count: int,
) -> None:
    cur.execute(
        """
        INSERT INTO content_blocks
          (book_id, chapter_id, block_index, char_start, char_end, char_count)
        VALUES (%s,%s,%s,%s,%s,%s)
        ON CONFLICT (book_id, chapter_id, block_index) DO UPDATE
        SET char_start = EXCLUDED.char_start,
            char_end = EXCLUDED.char_end,
            char_count = EXCLUDED.char_count
        """,
        (
            book_id,
            chapter_id,
            block_index,
            char_start,
            char_end,
            char_count,
        ),
    )


def insert_chapter_blocks(
    cur,
    book_id: int,
    chapter_id: int,
    blocks: List[Any],
    char_running: int,
) -> int:
    for block in blocks:
        for segment in block.segments:
            char_count = len(segment.text)
            char_start = char_running
            char_end = char_start + char_count

            insert_content_block(
                cur,
                book_id,
                chapter_id,
                segment.block_index,
                char_start,
                char_end,
                char_count,
            )

            char_running = char_end

    return char_running


def _fallback_book_title(file_path: Path, meta_title: Optional[str]) -> str:
    if meta_title and meta_title.strip():
        return meta_title
    return Path(file_path).stem


def _read_zip_resource(z: zipfile.ZipFile, meta: Dict,
                       href: str) -> tuple[bytes, str]:
    candidates: List[str] = []

    href_norm = normalize_zip_path(href)
    if href_norm:
        candidates.append(href_norm)

    opf_path = meta.get("opf_path") or ""
    if opf_path:
        candidates.append(resolve_href_relative(opf_path, href_norm))

    seen = set()

    for cand in candidates:
        cand = normalize_zip_path(cand)
        if not cand or cand in seen:
            continue

        seen.add(cand)

        actual = zip_actual_name(z, cand)
        if actual is not None:
            return z.read(actual), normalize_zip_path(actual)

    raise KeyError(href)


def _zip_resource_exists(z: zipfile.ZipFile, meta: Dict, href: str) -> bool:
    try:
        _read_zip_resource(z, meta, href)
        return True
    except KeyError:
        return False


def _preflight_check_spine_missing(
        z: zipfile.ZipFile, meta: Dict, args, file_name: str) -> bool:
    missing = 0
    max_warn = getattr(args, "warn_cap", 5)
    max_missing_spine = getattr(args, "max_missing_spine", 1)

    for href, media_type in meta.get("spine") or []:
        if not href or not href.lower().endswith((".xhtml", ".html", ".htm")):
            continue

        if _zip_resource_exists(z, meta, href):
            continue

        missing += 1

        if missing <= max_warn:
            print(f"[WARN] missing spine resource {href}", file=sys.stderr)

        if missing > max_missing_spine:
            print(
                f"[WARN] too many missing spine resources ({missing}) "
                f"> limit ({max_missing_spine}) → skip WHOLE book "
                f"(no Postgres, no ES) for {file_name}",
                file=sys.stderr,
            )
            return False

    if missing > 0:
        print(
            f"[WARN] missing spine resources total: {missing} (file: {file_name})",
            file=sys.stderr)

    return True


def _connect_from_args(args):
    dsn = getattr(args, "dsn", None)
    if not dsn:
        raise RuntimeError("args.dsn is required to connect to Postgres")
    return psycopg2.connect(dsn)


def _upload_cover_to_storage(
        z: zipfile.ZipFile, meta: Dict, book_id: int) -> None:
    cover_href = meta.get("cover_href")

    if not cover_href:
        return

    try:
        cover_bytes, resolved_href = _read_zip_resource(z, meta, cover_href)
    except KeyError:
        print(
            f"[WARN] cover image not found in ZIP: {cover_href}",
            file=sys.stderr)
        return

    ext = Path(resolved_href).suffix or ".jpg"

    put_bytes_sync(
        key=book_cover_key(book_id, ext),
        data=cover_bytes,
        content_type=cover_content_type(ext),
    )


def _upload_chapter_to_storage(
        book_id: int, chapter_id: int, html: str) -> None:
    _blocks, annotated_html = html_to_indexed_blocks(html)

    put_bytes_sync(
        key=chapter_key(book_id, chapter_id),
        data=annotated_html.encode("utf-8"),
        content_type="application/xhtml+xml; charset=utf-8",
    )


def _extract_chapter_payloads(z: zipfile.ZipFile, meta: Dict,
                              args, file_name: str) -> Optional[List[Dict[str, Any]]]:
    payloads: List[Dict[str, Any]] = []
    missing = 0
    max_warn = getattr(args, "warn_cap", 5)
    max_missing_spine = getattr(args, "max_missing_spine", 1)

    for c_idx, (href, media_type) in enumerate(
            meta.get("spine") or [], start=1):
        if not href or not href.lower().endswith((".xhtml", ".html", ".htm")):
            continue

        try:
            raw, resolved_href = _read_zip_resource(z, meta, href)
        except KeyError:
            missing += 1

            if missing <= max_warn:
                print(f"[WARN] missing spine resource {href}", file=sys.stderr)

            if missing > max_missing_spine:
                print(
                    f"[WARN] too many missing spine resources in content phase ({missing}) "
                    f"> limit ({max_missing_spine}) → skip WHOLE book for {file_name}",
                    file=sys.stderr,
                )
                return None

            continue

        html = raw.decode("utf-8", errors="ignore")

        chap_title = None
        try:
            soup = BeautifulSoup(html, "lxml")
            h = soup.find(["h1", "h2", "title"])
            chap_title = h.get_text().strip() if h else None
        except Exception:
            pass

        blocks, _annotated_html = html_to_indexed_blocks(html)

        if not args.no_join_short_paragraphs:
            blocks = coalesce_short_paragraphs(
                blocks, args.min_paragraph_words)

        block_token_counts = [len(tokenize_words(block.text))
                              for block in blocks]

        prefix = [0]
        for count in block_token_counts:
            prefix.append(prefix[-1] + count)

        wins = paragraph_windows(
            blocks,
            args.para_window_size,
            args.para_window_stride,
        )

        payloads.append(
            {
                "ord": c_idx,
                "href": resolved_href,
                "html": html,
                "title": chap_title,
                "blocks": blocks,
                "prefix": prefix,
                "wins": wins,
            }
        )

    if missing > 0:
        print(
            f"[WARN] missing spine resources total (content phase): {missing} (file: {file_name})",
            file=sys.stderr,
        )

    return payloads


def _emit_progress(
        progress_callback: Optional[Callable[[Dict[str, Any]], None]],
        **payload) -> None:
    if progress_callback is None:
        return

    progress_callback(payload)


def process_epub(
        file_path: Path,
        args,
        progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None):
    idx_meta: str = args.es_index_meta
    idx_content: str = args.es_index_content

    print(f"[INFO] Processing EPUB: {file_path.name}")
    _emit_progress(
        progress_callback,
        stage="parsing",
        status_label="Читаем EPUB",
        filename=file_path.name,
        progress_percent=2.0,
    )

    with zipfile.ZipFile(file_path, "r") as z:
        try:
            opf_path = parse_container_and_opf(z)
            meta = parse_opf(z, opf_path)
            _emit_progress(
                progress_callback,
                stage="metadata",
                status_label="Читаем метаданные",
                filename=file_path.name,
                title=_fallback_book_title(file_path, meta.get("title")),
                authors=", ".join(meta.get("creators") or []),
                progress_percent=6.0,
            )
        except Exception as e:
            print(
                f"[WARN] {
                    file_path.name}: OPF parse failed: {e}",
                file=sys.stderr)
            return "skipped"

        if not _preflight_check_spine_missing(z, meta, args, file_path.name):
            return "skipped"

        _emit_progress(
            progress_callback,
            stage="chapters",
            status_label="Разбираем главы",
            filename=file_path.name,
            title=_fallback_book_title(file_path, meta.get("title")),
            authors=", ".join(meta.get("creators") or []),
            progress_percent=10.0,
        )
        chapter_payloads = _extract_chapter_payloads(
            z, meta, args, file_path.name)

        if chapter_payloads is None:
            return "skipped"

        has_content = any(payload["wins"] for payload in chapter_payloads)

        if not has_content:
            print(
                f"[WARN] no content windows extracted → skip WHOLE book "
                f"(no Postgres, no ES) for {file_path.name}",
                file=sys.stderr,
            )
            return {
                "status": "skipped_empty_content",
                "filename": file_path.name,
                "chapters": len(chapter_payloads),
                "content_docs": 0,
            }

        conn = _connect_from_args(args)

        book_id: Optional[int] = None
        total_blocks_count = sum(len(payload['blocks'])
                                 for payload in chapter_payloads)

        try:
            with conn.cursor() as cur:
                book_id = find_or_insert_book(
                    cur, meta, meta["subjects"], total_blocks_count)
                delete_book_blocks(cur, book_id)

                book_title_for_es = _fallback_book_title(
                    file_path, meta.get("title"))
                book_authors_for_status = ", ".join(meta.get("creators") or [])
                _emit_progress(
                    progress_callback,
                    stage="database",
                    status_label="Сохраняем структуру книги",
                    filename=file_path.name,
                    title=book_title_for_es,
                    authors=book_authors_for_status,
                    progress_percent=15.0,
                )

                chapter_ids_by_ord: Dict[int, int] = {}

                for payload in chapter_payloads:
                    cid = insert_chapter(
                        cur,
                        book_id,
                        payload["ord"],
                        payload["title"],
                        len(payload['blocks'])
                    )
                    chapter_ids_by_ord[payload["ord"]] = cid

                meta_doc: Dict[str, Any] = {}
                content_docs: List[Dict[str, Any]] = []
                texts_for_embed: List[str] = []
                chars_running = 0
                words_running = 0

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

                for payload in chapter_payloads:
                    c_idx = payload["ord"]
                    chapter_id = chapter_ids_by_ord.get(c_idx)
                    blocks = payload["blocks"]
                    prefix = payload["prefix"]
                    wins = payload["wins"]

                    if chapter_id is None:
                        raise RuntimeError(
                            f"Chapter id not found for book_id={book_id}, ord={c_idx}"
                        )

                    chars_running = insert_chapter_blocks(
                        cur,
                        book_id,
                        chapter_id,
                        blocks,
                        chars_running,
                    )

                    base_offset = words_running

                    for win_idx, (start, end, win_blocks) in enumerate(wins):
                        para_text, block_offsets = build_window_content_and_offsets(
                            win_blocks)

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

                if not content_docs:
                    conn.rollback()
                    print(
                        f"[WARN] no content_docs generated → rollback Postgres and skip ES for {
                            file_path.name}",
                        file=sys.stderr,
                    )
                    return {
                        "status": "skipped_empty_content",
                        "book_id": book_id,
                        "title": book_title_for_es,
                        "chapters": len(chapter_ids_by_ord),
                        "content_docs": 0,
                    }

                dense_vec_dim = int(
                    getattr(
                        args,
                        "es_dense_vector_dim",
                        0) or 0)

                if args.embed_model:
                    total_vectors = len(texts_for_embed)
                    _emit_progress(
                        progress_callback,
                        stage="vectorizing",
                        status_label="Векторизуем фрагменты",
                        filename=file_path.name,
                        title=book_title_for_es,
                        authors=book_authors_for_status,
                        progress_percent=20.0,
                        current=0,
                        total=total_vectors,
                        unit="windows",
                    )
                    enc, enc_dev = get_encoder(
                        args.embed_model, device_mode=args.embed_device)

                    if dense_vec_dim <= 0:
                        dense_vec_dim = get_encoder_dim(
                            args.embed_model, enc_dev)

                    batch = args.embed_batch_size
                    vec_batches: List[np.ndarray] = []

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
                            vec_batches.append(embs)
                            current_vectors = min(
                                i + batch,
                                len(texts_for_embed),
                            )
                            vector_progress = (
                                current_vectors / total_vectors
                                if total_vectors
                                else 1.0
                            )
                            _emit_progress(
                                progress_callback,
                                stage="vectorizing",
                                status_label="Векторизуем фрагменты",
                                filename=file_path.name,
                                title=book_title_for_es,
                                authors=book_authors_for_status,
                                progress_percent=20.0 + vector_progress * 60.0,
                                current=current_vectors,
                                total=total_vectors,
                                unit="windows",
                            )

                    embeddings = (
                        np.vstack(vec_batches)
                        if vec_batches
                        else np.empty((0, dense_vec_dim), dtype=np.float32)
                    )

                    if len(embeddings) != len(content_docs):
                        raise RuntimeError(
                            f"Embedding count mismatch: vecs={
                                len(embeddings)}, content_docs={
                                len(content_docs)}"
                        )

                    for d, vec in zip(content_docs, embeddings):
                        d["content_vec"] = vec.astype(float).tolist()

                    if meta_doc:
                        book_vec = book_vector_from_window_embeddings(
                            embeddings,
                            step=2,
                        )
                        if book_vec is not None:
                            meta_doc["book_vec"] = book_vec

                if not args.no_es:
                    _emit_progress(
                        progress_callback,
                        stage="indexing",
                        status_label="Записываем индекс поиска",
                        filename=file_path.name,
                        title=book_title_for_es,
                        authors=book_authors_for_status,
                        progress_percent=84.0,
                        current=len(content_docs),
                        total=len(content_docs),
                        unit="documents",
                    )
                    ensure_es_indices(
                        args.es_url,
                        idx_meta,
                        idx_content,
                        store_source=not args.es_no_source,
                        use_templates=args.es_use_templates,
                        dense_vec_dim=dense_vec_dim,
                        enable_suggest=args.es_enable_suggest,
                    )

                    try:
                        es_bulk_atomic(
                            args.es_url,
                            idx_meta,
                            idx_content,
                            meta_doc,
                            content_docs,
                        )
                    except Exception:
                        conn.rollback()
                        raise

                try:
                    _emit_progress(
                        progress_callback,
                        stage="commit",
                        status_label="Сохраняем книгу",
                        filename=file_path.name,
                        title=book_title_for_es,
                        authors=book_authors_for_status,
                        progress_percent=90.0,
                    )
                    conn.commit()
                except Exception:
                    conn.rollback()

                    if not args.no_es and book_id is not None:
                        es_delete_book_docs(
                            args.es_url,
                            idx_meta,
                            idx_content,
                            book_id,
                        )

                    raise

                # MinIO/S3 upload is intentionally after DB+ES success.
                # It is not part of the DB+ES pseudo-transaction.
                _emit_progress(
                    progress_callback,
                    stage="uploading",
                    status_label="Сохраняем файлы книги",
                    filename=file_path.name,
                    title=book_title_for_es,
                    authors=book_authors_for_status,
                    progress_percent=92.0,
                    current=0,
                    total=len(chapter_payloads) + 1,
                    unit="files",
                )
                try:
                    _upload_cover_to_storage(z, meta, book_id)
                except Exception as e:
                    print(
                        f"[WARN] cannot upload cover to storage for book {book_id}: {e}",
                        file=sys.stderr)

                for chapter_upload_idx, payload in enumerate(chapter_payloads, start=1):
                    cid = chapter_ids_by_ord.get(payload["ord"])
                    if cid is None:
                        continue

                    try:
                        _upload_chapter_to_storage(
                            book_id, cid, payload["html"])
                    except Exception as e:
                        print(
                            f"[WARN] cannot upload chapter {cid} xml to storage: {e}",
                            file=sys.stderr)
                    upload_total = len(chapter_payloads) + 1
                    _emit_progress(
                        progress_callback,
                        stage="uploading",
                        status_label="Сохраняем файлы книги",
                        filename=file_path.name,
                        title=book_title_for_es,
                        authors=book_authors_for_status,
                        progress_percent=92.0
                        + (chapter_upload_idx / upload_total) * 7.0,
                        current=chapter_upload_idx + 1,
                        total=upload_total,
                        unit="files",
                    )

                _emit_progress(
                    progress_callback,
                    stage="completed",
                    status_label="Загрузка завершена",
                    filename=file_path.name,
                    title=book_title_for_es,
                    authors=book_authors_for_status,
                    progress_percent=100.0,
                )
                return {
                    "status": "ok",
                    "book_id": book_id,
                    "title": book_title_for_es,
                    "authors": book_authors_for_status,
                    "chapters": len(chapter_ids_by_ord),
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
