from pydantic import BaseModel
from uuid import UUID


class BookmarkDTO:
    bookmark_id: UUID

class UserBookmarksDTO:
    bookmarks: list[BookmarkDTO]

class CreateBookmarkDTO:
    offset: int
