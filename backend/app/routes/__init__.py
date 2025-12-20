from .search import router as search_router
from .books import router as books_router
from .reader import router as reader_router

# what will be imported after 'from routes import *'
__all__ = ["search_router", "books_router", "reader_router"]
