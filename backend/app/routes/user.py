from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import aliased

from app.dtos.books_dtos import BookCardDto, BookDto
from app.dtos.user import UserInfoDTO
from app.dtos.user_profile import ProfileReadingBookDto, ProfileReviewDto
from app.integrations.database import get_db_session
from app.integrations.object_storage import find_cover_key
from app.integrations.orm import Book, Review, User, t_reading_progress
from app.utils.auth import get_user_id

router = APIRouter(prefix="/user")


async def _get_cover_path(book_id: int) -> str | None:
    cover_key = await find_cover_key(book_id)

    if cover_key is None:
        return None

    return f"/books/{book_id}/cover"


def _book_card_dto(
    book: Book,
    cover_path: str | None,
    avg_rating,
    reviews_count,
) -> BookCardDto:
    return BookCardDto(
        book_id=book.id,
        title=book.title,
        cover_path=cover_path,
        authors=", ".join(book.authors or []),
        avg_rating=float(avg_rating) if avg_rating is not None else None,
        reviews_count=int(reviews_count or 0),
    )


def _book_dto(
    book: Book,
    cover_path: str | None,
    avg_rating,
    reviews_count,
) -> BookDto:
    return BookDto(
        book_id=book.id,
        title=book.title,
        lang=book.lang,
        description=book.description,
        publisher=book.publisher,
        pub_date=book.pub_date,
        subjects=None if book.subjects is None else ", ".join(book.subjects),
        series=book.series,
        cover_path=cover_path,
        authors=", ".join(book.authors or []),
        avg_rating=float(avg_rating) if avg_rating is not None else None,
        reviews_count=int(reviews_count or 0),
    )


@router.get("/info")
async def get_info(
    user_id: Annotated[UUID, Depends(get_user_id)],
) -> UserInfoDTO:
    async with get_db_session() as db_session:
        result = await db_session.execute(
            select(User).where(User.id == user_id)
        )
        user = result.scalar_one_or_none()

        if user is None:
            raise HTTPException(404, "User not found!")

        return UserInfoDTO(login=user.login, role=user.role)


async def _get_progress_books(
    user_id: UUID,
    finished: bool,
) -> list[ProfileReadingBookDto]:
    progress_table = t_reading_progress

    async with get_db_session() as db_session:
        stmt = (
            select(
                Book,
                progress_table.c.curr_chapter_id,
                progress_table.c.progress,
                func.avg(Review.rating).label("avg_rating"),
                func.count(Review.id).label("reviews_count"),
            )
            .join(Book, Book.id == progress_table.c.book_id)
            .outerjoin(Review, Review.book_id == Book.id)
            .where(progress_table.c.user_id == user_id)
            .where(
                progress_table.c.progress >= 100
                if finished
                else progress_table.c.progress < 100
            )
            .group_by(
                Book.id,
                progress_table.c.curr_chapter_id,
                progress_table.c.progress,
            )
            .order_by(Book.title)
        )
        rows = (await db_session.execute(stmt)).all()

    cover_paths = [await _get_cover_path(int(row[0].id)) for row in rows]

    return [
        ProfileReadingBookDto(
            book=_book_card_dto(
                row[0],
                cover_paths[idx],
                row[3],
                row[4],
            ),
            progress=int(row[2]),
            chapter_id=int(row[1]),
        )
        for idx, row in enumerate(rows)
    ]


@router.get("/profile/reading")
async def get_reading_books(
    user_id: Annotated[UUID, Depends(get_user_id)],
) -> list[ProfileReadingBookDto]:
    return await _get_progress_books(user_id, finished=False)


@router.get("/profile/finished")
async def get_finished_books(
    user_id: Annotated[UUID, Depends(get_user_id)],
) -> list[ProfileReadingBookDto]:
    return await _get_progress_books(user_id, finished=True)


@router.get("/profile/reviews")
async def get_my_reviews(
    user_id: Annotated[UUID, Depends(get_user_id)],
) -> list[ProfileReviewDto]:
    async with get_db_session() as db_session:
        UserReview = aliased(Review)
        AllReview = aliased(Review)
        progress_table = t_reading_progress
        stmt = (
            select(
                Book,
                UserReview,
                func.avg(AllReview.rating).label("avg_rating"),
                func.count(AllReview.id).label("reviews_count"),
                progress_table.c.progress,
                progress_table.c.curr_chapter_id,
            )
            .join(UserReview, UserReview.book_id == Book.id)
            .outerjoin(AllReview, AllReview.book_id == Book.id)
            .outerjoin(
                progress_table,
                (progress_table.c.book_id == Book.id)
                & (progress_table.c.user_id == user_id),
            )
            .where(UserReview.user_id == user_id)
            .group_by(
                Book.id,
                UserReview.id,
                progress_table.c.progress,
                progress_table.c.curr_chapter_id,
            )
            .order_by(
                func.coalesce(UserReview.updated_at, UserReview.created_at).desc()
            )
        )
        rows = (await db_session.execute(stmt)).all()

    cover_paths = [await _get_cover_path(int(row[0].id)) for row in rows]

    return [
        ProfileReviewDto(
            id=row[1].id,
            rating=row[1].rating,
            text=row[1].review_text,
            created_at=row[1].created_at,
            updated_at=row[1].updated_at,
            progress=None if row[4] is None else int(row[4]),
            chapter_id=None if row[5] is None else int(row[5]),
            book=_book_dto(
                row[0],
                cover_paths[idx],
                row[2],
                row[3],
            ),
        )
        for idx, row in enumerate(rows)
    ]
