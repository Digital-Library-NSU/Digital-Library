from .search import router as search_router
from .books import router as books_router

# what will be imported after 'from routes import *'
__all__ = ["search_router", "books_router"]
