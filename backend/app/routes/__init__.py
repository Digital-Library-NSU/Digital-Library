from .auth import router as auth_router
from .bookmarks import router as bookmarks_router
from .books import router as books_router
from .read_prog import router as read_prog_router
from .reader import router as reader_router
from .reviews import router as review_router
from .search import router as search_router
from .user import router as user_router

# what will be imported after 'from routes import *'
__all__ = [
    "search_router",
    "books_router",
    "reader_router",
    "auth_router",
    "user_router",
    "review_router",
    "bookmarks_router",
    "read_prog_router"]
