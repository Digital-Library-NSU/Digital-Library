from pathlib import Path
from uuid import uuid4
import asyncio
import json
from typing import Any, Literal
from celery.result import AsyncResult
from fastapi import APIRouter, HTTPException, Request, UploadFile, File
from fastapi.responses import Response, StreamingResponse
import redis
from sqlalchemy import delete, func, select

from app.celery_app import celery_app
from app.config import CELERY_RESULT_BACKEND, ES_URL, IDX_CONTENT, IDX_META, UPLOAD_TMP_DIR
from app.dtos.books_dtos import (
    BookCardDto,
    BookDto,
    UploadBookResponseDto,
    ImportTaskStatusDto,
    CancelImportResponseDto,
)
from app.integrations.database import get_db_session
from app.integrations.elasticsearch import es_post
from app.import_epub.es_support import es_delete_book_docs
from app.integrations.object_storage import delete_book_objects, find_cover_key, get_object_bytes
from app.integrations.orm import Book, Review, User, t_reading_progress
from app.tasks.import_tasks import import_epub_task
from app.utils.auth import get_user_id

router = APIRouter(prefix="/books")

IMPORT_TASK_META_TTL_SECONDS = 60 * 60 * 24

RECOMMENDATION_SOURCE_LIMIT = 5
RECOMMENDATION_CANDIDATE_POOL_SIZE = 50
RECOMMENDATION_MIN_SEMANTIC_SCORE = 0.75
RECOMMENDATION_RELATIVE_SCORE_RATIO = 0.95
RECOMMENDATION_CONTENT_POOL_SIZE = 300


async def _get_cover_path(book_id: int) -> str | None:
    cover_key = await find_cover_key(book_id)

    if cover_key is None:
        return None

    return f"/books/{book_id}/cover"


async def _require_admin(request: Request) -> None:
    user_id = await get_user_id(request)

    async with get_db_session() as db_session:
        user = await db_session.get(User, user_id)

    if user is None or user.role != "admin":
        raise HTTPException(403, "Admin access required")


def _average_vectors(vectors: list[list[float]]) -> list[float] | None:
    if not vectors:
        return None

    dim = len(vectors[0])
    sums = [0.0] * dim
    valid_count = 0

    for vec in vectors:
        if len(vec) != dim:
            continue

        for idx, value in enumerate(vec):
            sums[idx] += float(value)
        valid_count += 1

    if valid_count == 0:
        return None

    count = float(valid_count)
    mean = [value / count for value in sums]
    norm = sum(value * value for value in mean) ** 0.5

    if norm <= 0:
        return None

    return [value / norm for value in mean]


def _extract_book_vec(hit) -> list[float] | None:
    source_vec = hit.get("_source", {}).get("book_vec")
    if source_vec:
        return source_vec

    field_vec = hit.get("fields", {}).get("book_vec")
    if isinstance(field_vec, list) and field_vec:
        first = field_vec[0]
        if isinstance(first, list):
            return first

    return None


def _extract_book_id(hit) -> int | None:
    source_book_id = hit.get("_source", {}).get("book_id")
    raw_book_id = source_book_id if source_book_id is not None else hit.get("_id")

    try:
        return int(raw_book_id)
    except Exception:
        return None


async def _book_cards_by_ids(book_ids: list[int]) -> list[BookCardDto]:
    if not book_ids:
        return []

    async with get_db_session() as db_session:
        stmt = (
            select(
                Book,
                func.avg(Review.rating).label("avg_rating"),
                func.count(Review.id).label("reviews_count"),
            )
            .outerjoin(Review, Review.book_id == Book.id)
            .where(Book.id.in_(book_ids))
            .group_by(Book.id)
        )
        rows = (await db_session.execute(stmt)).all()

    rows_by_id = {int(row[0].id): row for row in rows}
    cover_paths = {
        book_id: await _get_cover_path(book_id)
        for book_id in book_ids
        if book_id in rows_by_id
    }

    result: list[BookCardDto] = []
    for book_id in book_ids:
        row = rows_by_id.get(book_id)
        if row is None:
            continue

        book = row[0]
        result.append(
            BookCardDto(
                book_id=book.id,
                title=book.title,
                cover_path=cover_paths.get(book_id),
                authors=", ".join(book.authors or []),
                avg_rating=float(row.avg_rating)
                if row.avg_rating is not None
                else None,
                reviews_count=int(row.reviews_count),
            )
        )

    return result


def _normalize_terms(values: list[str] | None) -> set[str]:
    if not values:
        return set()

    return {
        value.strip().lower()
        for value in values
        if value and value.strip()
    }


def _filter_recommendation_candidates(
    candidates: list[tuple[int, float]],
) -> list[tuple[int, float]]:
    if not candidates:
        return []

    sorted_candidates = sorted(candidates, key=lambda item: item[1], reverse=True)
    best_score = sorted_candidates[0][1]
    relative_threshold = best_score * RECOMMENDATION_RELATIVE_SCORE_RATIO

    filtered: list[tuple[int, float]] = []

    for book_id, score in sorted_candidates:
        if score < relative_threshold:
            break

        filtered.append((book_id, score))

    return filtered


async def _recommendation_metadata_scores(
    source_book_ids: list[int],
    candidate_ids: list[int],
) -> dict[int, dict[str, float | str]]:
    all_book_ids = sorted(set(source_book_ids + candidate_ids))

    async with get_db_session() as db_session:
        stmt = (
            select(
                Book.id,
                Book.title,
                Book.authors,
                Book.subjects,
            )
            .where(Book.id.in_(all_book_ids))
        )
        rows = (await db_session.execute(stmt)).all()

    meta_by_id: dict[int, dict[str, Any]] = {
        int(row.id): {
            "title": row.title,
            "authors": _normalize_terms(row.authors),
            "subjects": _normalize_terms(row.subjects),
        }
        for row in rows
    }

    source_authors: set[str] = set()
    source_subjects: set[str] = set()
    for book_id in source_book_ids:
        source_meta = meta_by_id.get(book_id)
        if not source_meta:
            continue

        source_authors.update(source_meta["authors"])
        source_subjects.update(source_meta["subjects"])

    scores: dict[int, dict[str, float | str]] = {}
    for book_id in candidate_ids:
        candidate_meta = meta_by_id.get(book_id)
        if not candidate_meta:
            continue

        candidate_authors = candidate_meta["authors"]
        candidate_subjects = candidate_meta["subjects"]
        author_score = 1.0 if source_authors & candidate_authors else 0.0
        subject_union = source_subjects | candidate_subjects
        subject_score = (
            len(source_subjects & candidate_subjects) / len(subject_union)
            if subject_union
            else 0.0
        )

        scores[book_id] = {
            "title": str(candidate_meta["title"]),
            "author_score": author_score,
            "subject_score": subject_score,
            "meta_score": author_score * 0.80 + subject_score * 0.20,
        }

    return scores


async def _content_scores_for_recommendations(
    user_vec: list[float],
    candidate_ids: list[int],
    excluded_book_ids: list[int],
) -> dict[int, dict[str, float]]:
    if not candidate_ids:
        return {}

    content_pool_size = max(
        RECOMMENDATION_CONTENT_POOL_SIZE,
        len(candidate_ids) * 20,
    )
    res = await es_post(
        f"{IDX_CONTENT}/_search",
        {
            "size": content_pool_size,
            "knn": {
                "field": "content_vec",
                "query_vector": user_vec,
                "k": content_pool_size,
                "num_candidates": max(500, content_pool_size * 10),
                "filter": {
                    "bool": {
                        "filter": [
                            {
                                "terms": {
                                    "book_id": [
                                        str(book_id)
                                        for book_id in candidate_ids
                                    ]
                                }
                            }
                        ],
                        "must_not": [
                            {
                                "terms": {
                                    "book_id": [
                                        str(book_id)
                                        for book_id in excluded_book_ids
                                    ]
                                }
                            }
                        ],
                    }
                },
            },
            "_source": ["book_id"],
        },
    )

    scores: dict[int, dict[str, float]] = {}
    for hit in res.get("hits", {}).get("hits", []):
        try:
            book_id = int(hit.get("_source", {}).get("book_id"))
        except Exception:
            continue

        score = float(hit.get("_score") or 0.0)
        current = scores.setdefault(
            book_id,
            {
                "max_score": 0.0,
                "sum_score": 0.0,
                "hits_count": 0.0,
            },
        )
        current["max_score"] = max(current["max_score"], score)
        current["sum_score"] += score
        current["hits_count"] += 1.0

    return scores


async def _rank_recommendations_semantically(
    user_vec: list[float],
    candidates: list[tuple[int, float]],
    excluded_book_ids: list[int],
    source_book_ids: list[int],
) -> list[int]:
    filtered_candidates = _filter_recommendation_candidates(candidates)
    if not filtered_candidates:
        return []

    candidate_ids = [book_id for book_id, _score in filtered_candidates]
    metadata_scores, content_scores = await asyncio.gather(
        _recommendation_metadata_scores(source_book_ids, candidate_ids),
        _content_scores_for_recommendations(
            user_vec,
            candidate_ids,
            excluded_book_ids,
        ),
    )

    if not content_scores:
        return candidate_ids

    max_book_score = max(score for _book_id, score in filtered_candidates)
    max_content_score = max(
        score["max_score"]
        for score in content_scores.values()
    )
    max_hits_count = max(
        score["hits_count"]
        for score in content_scores.values()
    )

    ranked: list[tuple[int, float]] = []
    for book_id, book_score in filtered_candidates:
        content_score = content_scores.get(book_id)
        if content_score is None:
            continue

        metadata_score = metadata_scores.get(book_id, {})
        book_norm = book_score / max_book_score if max_book_score > 0 else 0.0
        content_norm = (
            content_score["max_score"] / max_content_score
            if max_content_score > 0
            else 0.0
        )
        content_hits_norm = (
            content_score["hits_count"] / max_hits_count
            if max_hits_count > 0
            else 0.0
        )
        meta_score = float(metadata_score.get("meta_score", 0.0))
        final_score = (
            book_norm * 0.35
            + content_norm * 0.40
            + content_hits_norm * 0.10
            + meta_score * 0.15
        )
        ranked.append((book_id, final_score))

        print(
            "[recommendations:score] "
            f"book_id={book_id} "
            f"title={metadata_score.get('title', '')!r} "
            f"book_score={book_score:.6f} "
            f"book_norm={book_norm:.6f} "
            f"content_max_score={content_score['max_score']:.6f} "
            f"content_hits={int(content_score['hits_count'])} "
            f"content_norm={content_norm:.6f} "
            f"content_hits_norm={content_hits_norm:.6f} "
            f"meta_score={meta_score:.6f} "
            f"final_score={final_score:.6f}"
        )

    ranked.sort(key=lambda item: item[1], reverse=True)
    print(
        "[recommendations:score] "
        f"ranked_ids={[book_id for book_id, _score in ranked]}"
    )
    return [book_id for book_id, _score in ranked]


async def _get_recommended_books(
    request: Request,
    limit: int | None,
    offset: int,
) -> list[BookCardDto]:
    user_id = await get_user_id(request)
    page_limit = limit or 12

    async with get_db_session() as db_session:
        progress_rows = (
            await db_session.execute(
                select(
                    t_reading_progress.c.book_id,
                    t_reading_progress.c.progress,
                )
                .where(t_reading_progress.c.user_id == user_id)
                .order_by(t_reading_progress.c.updated_at.desc())
            )
        ).all()

    if not progress_rows:
        return []

    excluded_book_ids = [int(row[0]) for row in progress_rows]
    excluded_book_ids_set = set(excluded_book_ids)
    source_book_ids = [
        int(row[0])
        for row in progress_rows[:RECOMMENDATION_SOURCE_LIMIT]
    ]

    source_res = await es_post(
        f"{IDX_META}/_search",
        {
            "size": len(source_book_ids),
            "query": {"ids": {"values": [str(book_id) for book_id in source_book_ids]}},
            "_source": ["book_id", "book_vec"],
            "fields": ["book_vec"],
        },
    )

    source_vectors = [
        _extract_book_vec(hit)
        for hit in source_res.get("hits", {}).get("hits", [])
    ]
    source_vectors = [vec for vec in source_vectors if vec]
    user_vec = _average_vectors(source_vectors)

    if user_vec is None:
        return []

    search_size = max(
        page_limit + offset,
        RECOMMENDATION_CANDIDATE_POOL_SIZE,
    ) + len(excluded_book_ids)
    rec_res = await es_post(
        f"{IDX_META}/_search",
        {
            "size": search_size,
            "min_score": RECOMMENDATION_MIN_SEMANTIC_SCORE,
            "knn": {
                "field": "book_vec",
                "query_vector": user_vec,
                "k": search_size,
                "num_candidates": max(100, search_size * 20),
            },
            "_source": ["book_id"],
        },
    )

    candidates: list[tuple[int, float]] = []
    for hit in rec_res.get("hits", {}).get("hits", []):
        book_id = _extract_book_id(hit)
        if book_id is None:
            continue

        if book_id in excluded_book_ids_set:
            continue

        candidates.append((book_id, float(hit.get("_score") or 0.0)))

    recommended_ids = await _rank_recommendations_semantically(
        user_vec,
        candidates,
        excluded_book_ids,
        source_book_ids,
    )
    return await _book_cards_by_ids(recommended_ids[offset : offset + page_limit])


@router.get("/all")
async def get_all_books(
    request: Request,
    limit: int | None = None,
    offset: int = 0,
    sort: Literal["popular", "new", "recommended"] = "popular",
) -> list[BookCardDto]:
    if sort == "recommended":
        return await _get_recommended_books(request, limit, offset)

    async with get_db_session() as db_session:
        stmt = (
            select(
                Book,
                func.avg(Review.rating).label("avg_rating"),
                func.count(Review.id).label("reviews_count"),
            )
            .outerjoin(Review, Review.book_id == Book.id)
            .group_by(Book.id)
            .offset(offset)
        )

        if sort == "new":
            stmt = stmt.order_by(Book.added_at.desc(), Book.id.desc())
        else:
            stmt = stmt.order_by(
                func.avg(Review.rating).desc().nullslast(),
                func.count(Review.id).desc(),
                Book.id,
            )

        if limit is not None:
            stmt = stmt.limit(limit)

        result = await db_session.execute(stmt)
        rows = result.all()

    cover_paths = [
        await _get_cover_path(int(row.Book.id))
        for row in rows
    ]

    return [
        BookCardDto(
            book_id=row.Book.id,
            title=row.Book.title,
            cover_path=cover_paths[idx],
            authors=", ".join(row.Book.authors or []),
            avg_rating=float(row.avg_rating) if row.avg_rating is not None else None,
            reviews_count=int(row.reviews_count),
        )
        for idx, row in enumerate(rows)
    ]


@router.get("/{book_id}/cover")
async def get_book_cover(book_id: int) -> Response:
    cover_key = await find_cover_key(book_id)

    if cover_key is None:
        raise HTTPException(404, "Cover not found")

    try:
        data, content_type = await get_object_bytes(cover_key)
    except FileNotFoundError:
        raise HTTPException(404, "Cover not found")

    return Response(
        content=data,
        media_type=content_type,
    )


@router.get("/{book_id}")
async def get_book_by_id(book_id: int) -> BookDto:
    async with get_db_session() as db_session:
        stmt = (
            select(
                Book,
                func.avg(Review.rating).label("avg_rating"),
                func.count(Review.id).label("reviews_count"),
            )
            .outerjoin(Review, Review.book_id == Book.id)
            .where(Book.id == book_id)
            .group_by(Book.id)
        )

        result = await db_session.execute(stmt)
        row = result.first()

        if row is None:
            raise HTTPException(404, "Book not found!")

        book = row.Book

    return BookDto(
        book_id=book.id,
        title=book.title,
        lang=book.lang,
        description=book.description,
        publisher=book.publisher,
        pub_date=book.pub_date,
        subjects=None if book.subjects is None else ", ".join(book.subjects),
        series=book.series,
        cover_path=await _get_cover_path(book.id),
        authors=", ".join(book.authors or []),
        avg_rating=float(row.avg_rating) if row.avg_rating is not None else None,
        reviews_count=int(row.reviews_count),
    )


@router.delete("/{book_id}", status_code=204)
async def delete_book(book_id: int, request: Request) -> Response:
    await _require_admin(request)

    async with get_db_session() as db_session:
        book_exists = await db_session.scalar(
            select(Book.id).where(Book.id == book_id)
        )
        if book_exists is None:
            raise HTTPException(404, "Book not found!")

        await db_session.execute(
            delete(Book).where(Book.id == book_id)
        )
        await db_session.commit()

    await asyncio.to_thread(
        es_delete_book_docs,
        ES_URL,
        IDX_META,
        IDX_CONTENT,
        book_id,
    )
    await delete_book_objects(book_id)

    return Response(status_code=204)


@router.post("/upload", response_model=UploadBookResponseDto, status_code=202)
async def upload_book(file: UploadFile = File(...)) -> UploadBookResponseDto:
    if not file.filename or not file.filename.lower().endswith(".epub"):
        raise HTTPException(status_code=400, detail="Требуется EPUB файл")

    upload_dir = Path(UPLOAD_TMP_DIR)
    upload_dir.mkdir(parents=True, exist_ok=True)

    safe_name = Path(file.filename).name
    tmp_path = upload_dir / f"{uuid4()}_{safe_name}"

    content = await file.read()
    tmp_path.write_bytes(content)

    task = import_epub_task.delay(
        str(tmp_path),
        safe_name,
    )
    _save_import_task_meta(
        task.id,
        {
            "filename": safe_name,
            "tmp_path": str(tmp_path),
        },
    )

    return UploadBookResponseDto(
        task_id=task.id,
        status="queued",
        filename=safe_name,
    )


def _import_task_meta_key(task_id: str) -> str:
    return f"library:import-task:{task_id}"


def _get_import_task_meta(task_id: str) -> dict[str, Any]:
    try:
        client = redis.Redis.from_url(CELERY_RESULT_BACKEND, decode_responses=True)
        raw = client.get(_import_task_meta_key(task_id))
    except Exception:
        return {}

    if not raw:
        return {}

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}

    return data if isinstance(data, dict) else {}


def _save_import_task_meta(task_id: str, payload: dict[str, Any]) -> None:
    try:
        client = redis.Redis.from_url(CELERY_RESULT_BACKEND, decode_responses=True)
        client.setex(
            _import_task_meta_key(task_id),
            IMPORT_TASK_META_TTL_SECONDS,
            json.dumps(payload),
        )
    except Exception:
        pass


def _delete_import_task_meta(task_id: str) -> None:
    try:
        client = redis.Redis.from_url(CELERY_RESULT_BACKEND, decode_responses=True)
        client.delete(_import_task_meta_key(task_id))
    except Exception:
        pass


def _delete_import_tmp_file(raw_path: Any) -> None:
    if not isinstance(raw_path, str) or not raw_path:
        return

    upload_root = Path(UPLOAD_TMP_DIR).resolve()
    tmp_path = Path(raw_path).resolve()

    if upload_root not in tmp_path.parents:
        return

    tmp_path.unlink(missing_ok=True)


@router.delete("/imports/{task_id}", response_model=CancelImportResponseDto)
async def cancel_import(task_id: str) -> CancelImportResponseDto:
    meta = await asyncio.to_thread(_get_import_task_meta, task_id)
    task = AsyncResult(task_id, app=celery_app)

    task.revoke(terminate=True, signal="SIGKILL")
    await asyncio.to_thread(_delete_import_tmp_file, meta.get("tmp_path"))
    await asyncio.to_thread(task.forget)
    await asyncio.to_thread(_delete_import_task_meta, task_id)

    return CancelImportResponseDto(
        task_id=task_id,
        state="REVOKED",
        stage="cancelled",
        status_label="Импорт отменен",
        filename=meta.get("filename") if isinstance(meta.get("filename"), str) else None,
    )


def _status_from_payload(payload: dict | None) -> dict:
    if not isinstance(payload, dict):
        return {}

    status_payload = payload.get("status")
    if isinstance(status_payload, dict):
        merged = {**payload, **status_payload}
        return merged

    return payload


def _human_import_error(raw_error: str | None) -> str | None:
    if not raw_error:
        return None

    lower_error = raw_error.lower()
    if (
        "workerlosterror" in lower_error
        or "sigkill" in lower_error
        or "signal 9" in lower_error
        or "exited prematurely" in lower_error
    ):
        return (
            "Out of Memory: RAM"
        )

    return raw_error


def _get_import_status_sync(task_id: str) -> ImportTaskStatusDto:
    task = AsyncResult(task_id, app=celery_app)

    raw_error = str(task.result) if task.failed() else None
    error = _human_import_error(raw_error)

    result = None
    if task.successful():
        result = task.result
    elif isinstance(task.info, dict):
        result = task.info

    payload = _status_from_payload(result if isinstance(result, dict) else None)
    state = task.state

    queued = state == "PENDING"
    stage = payload.get("stage")
    status_label = payload.get("status_label")
    progress_percent = payload.get("progress_percent")

    if queued:
        stage = "queued"
        status_label = "Книга в очереди"
        progress_percent = 0.0
    elif task.successful():
        stage = "completed"
        status_label = "Загрузка завершена"
        progress_percent = 100.0
    elif task.failed():
        stage = "failed"
        if error != raw_error:
            status_label = "Недостаточно памяти"
        status_label = "Ошибка импорта"

    if task.failed() and error != raw_error:
        status_label = "Недостаточно памяти"

    return ImportTaskStatusDto(
        task_id=task_id,
        state=state,
        filename=payload.get("filename"),
        title=payload.get("title"),
        authors=payload.get("authors"),
        stage=stage,
        status_label=status_label,
        progress_percent=progress_percent,
        current=payload.get("current"),
        total=payload.get("total"),
        unit=payload.get("unit"),
        eta_seconds=payload.get("eta_seconds"),
        queued=queued,
        started_at=payload.get("started_at"),
        updated_at=payload.get("updated_at"),
        result=result,
        error=error,
    )


def _terminal_import_status(status: ImportTaskStatusDto) -> bool:
    return (
        status.state in {"SUCCESS", "FAILURE", "REVOKED"}
        or status.stage in {"completed", "failed", "cancelled"}
    )


def _sse_payload(status: ImportTaskStatusDto) -> str:
    payload = status.model_dump(mode="json")
    return f"event: import-status\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


@router.get("/imports/events")
async def stream_import_statuses(
    request: Request,
    ids: str,
) -> StreamingResponse:
    task_ids = [
        task_id.strip()
        for task_id in ids.split(",")
        if task_id.strip()
    ]

    async def event_stream():
        last_payloads: dict[str, str] = {}
        active_task_ids = set(task_ids)

        while active_task_ids:
            if await request.is_disconnected():
                break

            finished_task_ids: set[str] = set()

            for task_id in list(active_task_ids):
                status = await asyncio.to_thread(_get_import_status_sync, task_id)
                payload_key = json.dumps(
                    status.model_dump(mode="json"),
                    sort_keys=True,
                    ensure_ascii=False,
                )

                if last_payloads.get(task_id) != payload_key:
                    last_payloads[task_id] = payload_key
                    yield _sse_payload(status)

                if _terminal_import_status(status):
                    finished_task_ids.add(task_id)

            active_task_ids.difference_update(finished_task_ids)

            if active_task_ids:
                await asyncio.sleep(2)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/imports/{task_id}", response_model=ImportTaskStatusDto)
async def get_import_status(task_id: str) -> ImportTaskStatusDto:
    return await asyncio.to_thread(_get_import_status_sync, task_id)
