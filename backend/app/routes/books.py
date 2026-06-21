from pathlib import Path
from uuid import uuid4
import asyncio
import datetime
from typing import Literal
from celery.result import AsyncResult
from fastapi import APIRouter, HTTPException, Request, UploadFile, File
from fastapi.responses import Response
from sqlalchemy import func, select

from app.celery_app import celery_app
from app.config import IDX_META, UPLOAD_TMP_DIR
from app.dtos.books_dtos import (
    BookCardDto,
    BookDto,
    UploadBookResponseDto,
    ImportTaskStatusDto,
)
from app.integrations.database import get_db_session
from app.integrations.elasticsearch import es_post
from app.integrations.object_storage import find_cover_key, get_object_bytes
from app.integrations.orm import Book, Review, t_reading_progress
from app.tasks.import_tasks import import_epub_task
from app.utils.auth import get_user_id

router = APIRouter(prefix="/books")

RECOMMENDATION_SOURCE_LIMIT = 5
RECOMMENDATION_CANDIDATE_POOL_SIZE = 50
RECOMMENDATION_MIN_SEMANTIC_SCORE = 0.75


async def _get_cover_path(book_id: int) -> str | None:
    cover_key = await find_cover_key(book_id)

    if cover_key is None:
        return None

    return f"/books/{book_id}/cover"


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


async def _rerank_recommendations(
    candidates: list[tuple[int, float]],
) -> list[int]:
    if not candidates:
        return []

    book_ids = [book_id for book_id, _score in candidates]

    async with get_db_session() as db_session:
        stmt = (
            select(
                Book.id,
                Book.added_at,
                func.avg(Review.rating).label("avg_rating"),
                func.count(Review.id).label("reviews_count"),
            )
            .outerjoin(Review, Review.book_id == Book.id)
            .where(Book.id.in_(book_ids))
            .group_by(Book.id)
        )
        rows = (await db_session.execute(stmt)).all()

    stats_by_id = {
        int(row.id): {
            "added_at": row.added_at,
            "avg_rating": float(row.avg_rating) if row.avg_rating is not None else None,
            "reviews_count": int(row.reviews_count),
        }
        for row in rows
    }

    max_semantic_score = max((score for _book_id, score in candidates), default=0.0)
    now = datetime.datetime.utcnow()

    scored_ids: list[tuple[int, float]] = []
    for book_id, semantic_score in candidates:
        stats = stats_by_id.get(book_id)
        if stats is None:
            continue

        semantic_norm = (
            semantic_score / max_semantic_score
            if max_semantic_score > 0
            else 0.0
        )
        rating_score = (
            stats["avg_rating"] / 10.0
            if stats["avg_rating"] is not None
            else 0.0
        )
        review_score = min(stats["reviews_count"], 10) / 10.0

        added_at = stats["added_at"]
        if added_at is not None:
            age_days = max(0, (now - added_at).days)
            freshness_score = 1.0 / (1.0 + age_days / 365.0)
        else:
            freshness_score = 0.0

        final_score = (
            semantic_norm * 0.80
            + rating_score * 0.12
            + review_score * 0.05
            + freshness_score * 0.03
        )
        scored_ids.append((book_id, final_score))

    scored_ids.sort(key=lambda item: item[1], reverse=True)
    return [book_id for book_id, _score in scored_ids]


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

    source_book_ids = [
        int(row[0])
        for row in progress_rows[:RECOMMENDATION_SOURCE_LIMIT]
    ]
    excluded_book_ids = [int(row[0]) for row in progress_rows]

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

    excluded_book_ids_set = set(excluded_book_ids)
    candidates: list[tuple[int, float]] = []
    for hit in rec_res.get("hits", {}).get("hits", []):
        book_id = _extract_book_id(hit)
        if book_id is None:
            continue

        if book_id in excluded_book_ids_set:
            continue

        candidates.append((book_id, float(hit.get("_score") or 0.0)))

    recommended_ids = await _rerank_recommendations(candidates)
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

    return UploadBookResponseDto(
        task_id=task.id,
        status="queued",
    )


def _get_import_status_sync(task_id: str) -> ImportTaskStatusDto:
    task = AsyncResult(task_id, app=celery_app)

    error = str(task.result) if task.failed() else None

    result = None
    if task.successful():
        result = task.result
    elif isinstance(task.info, dict):
        result = task.info

    return ImportTaskStatusDto(
        task_id=task_id,
        state=task.state,
        result=result,
        error=error,
    )


@router.get("/imports/{task_id}", response_model=ImportTaskStatusDto)
async def get_import_status(task_id: str) -> ImportTaskStatusDto:
    return await asyncio.to_thread(_get_import_status_sync, task_id)
