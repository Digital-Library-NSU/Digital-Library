from datetime import datetime

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.dtos.review import CreateReviewDTO, ReviewDTO
from app.integrations.database import get_db_session
from app.integrations.orm import Book, Review
from app.routes.auth import get_current_user

router = APIRouter(prefix="/books")


@router.post("/{book_id}/review")
async def upsert_review(
    book_id: int,
    dto: CreateReviewDTO,
    request: Request,
) -> ReviewDTO:
    user = await get_current_user(request)

    async with get_db_session() as db_session:
        book = await db_session.get(Book, book_id)

        if book is None:
            raise HTTPException(404, "Book not found!")

        result = await db_session.execute(
            select(Review).where(
                Review.user_id == user.id,
                Review.book_id == book_id,
            )
        )

        existing_review = result.scalar_one_or_none()

        if existing_review is None:
            review = Review()
            review.user_id = user.id
            review.book_id = book_id
            db_session.add(review)
        else:
            review = existing_review
            review.updated_at = datetime.utcnow()

        review.rating = dto.rating
        review.review_text = dto.text

        await db_session.commit()
        await db_session.refresh(review)

        return ReviewDTO(
            id=review.id,
            user_login=user.login,
            rating=review.rating,
            text=review.review_text,
            created_at=review.created_at,
            updated_at=review.updated_at,
        )


@router.get("/{book_id}/my-review")
async def get_my_review(
    book_id: int,
    request: Request,
) -> ReviewDTO:
    user = await get_current_user(request)

    async with get_db_session() as db_session:
        result = await db_session.execute(
            select(Review)
            .options(selectinload(Review.user))
            .where(
                Review.user_id == user.id,
                Review.book_id == book_id,
            )
        )

        review = result.scalar_one_or_none()

        if review is None:
            raise HTTPException(404, "Review not found!")

        return ReviewDTO(
            id=review.id,
            user_login=review.user.login,
            rating=review.rating,
            text=review.review_text,
            created_at=review.created_at,
            updated_at=review.updated_at,
        )


@router.get("/{book_id}/reviews")
async def get_book_reviews(
    book_id: int,
) -> list[ReviewDTO]:
    async with get_db_session() as db_session:
        book = await db_session.get(Book, book_id)

        if book is None:
            raise HTTPException(404, "Book not found!")

        result = await db_session.execute(
            select(Review)
            .options(selectinload(Review.user))
            .where(Review.book_id == book_id)
            .order_by(func.coalesce(Review.updated_at, Review.created_at).desc())
        )

        reviews = result.scalars().all()

        return [
            ReviewDTO(
                id=review.id,
                user_login=review.user.login,
                rating=review.rating,
                text=review.review_text,
                created_at=review.created_at,
                updated_at=review.updated_at,
            )
            for review in reviews
        ]


@router.delete("/reviews/{review_id}")
async def delete_review(
    review_id: int,
    request: Request,
):
    user = await get_current_user(request)

    async with get_db_session() as db_session:
        review = await db_session.get(Review, review_id)

        if review is None:
            raise HTTPException(404, "Review not found!")

        if review.user_id != user.id:
            raise HTTPException(403, "Forbidden!")

        await db_session.delete(review)
        await db_session.commit()

    return {"ok": True}
