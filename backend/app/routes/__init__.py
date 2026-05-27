from .search import router as search_router
from .books import router as books_router
from .reader import router as reader_router
from .auth import router as auth_router
from .user import router as user_router
from .reviews import router as review_router

# what will be imported after 'from routes import *'
__all__ = [
    "search_router",
    "books_router",
    "reader_router",
    "auth_router",
    "user_router",
    "review_router"]
