from datetime import datetime

from pydantic import BaseModel, Field


class CreateReviewDTO(BaseModel):
    rating: int = Field(ge=1, le=10)
    text: str


class ReviewDTO(BaseModel):
    id: int

    user_login: str

    rating: int
    text: str

    created_at: datetime
    updated_at: datetime | None = None
