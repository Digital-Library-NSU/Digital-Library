from fastapi import APIRouter, HTTPException

from app.dtos.books_dtos import BookCardDto, BookDto
from datetime import datetime

router = APIRouter(prefix="/books")


mocked_books = [
    BookDto(authors="Джейсон Шрейер", book_id=0, cover_path=None, title="Кровь, пот и пиксели", lang="ru", description="Закулисные истории создания видеоигр",
            publisher="Манн, Иванов и Фербер", pub_date=datetime(2018, 1, 1), subjects="Игровая индустрия, разработка", series=None),
    BookDto(authors="Антон Чехов", book_id=1, cover_path=None, title="Ионыч", lang="ru", description="История духовной деградации земского врача",
            publisher="Разные издания", pub_date=datetime(1898, 1, 1), subjects="Русская классика, проза", series=None),
    BookDto(authors="Михаил Булгаков", book_id=2, cover_path=None, title="Мастер и Маргарита", lang="ru", description="Философский роман о добре и зле",
            publisher="Художественная литература", pub_date=datetime(1966, 1, 1), subjects="Фантастика, философия", series=None),
    BookDto(authors="Джордж Оруэлл", book_id=3, cover_path=None, title="1984", lang="en", description="Антиутопия о тоталитарном обществе",
            publisher="Secker & Warburg", pub_date=datetime(1949, 6, 8), subjects="Антиутопия, политика", series=None),
    BookDto(authors="Антуан де Сент-Экзюпери", book_id=4, cover_path=None, title="Маленький принц", lang="fr", description="Философская сказка-притча",
            publisher="Reynal & Hitchcock", pub_date=datetime(1943, 4, 6), subjects="Философия, сказка", series=None),
    BookDto(authors="Фёдор Достоевский", book_id=5, cover_path=None, title="Преступление и наказание", lang="ru", description="Роман о моральных терзаниях убийцы",
            publisher="Русский вестник", pub_date=datetime(1866, 1, 1), subjects="Психология, философия", series=None),
    BookDto(authors="Джоан Роулинг", book_id=6, cover_path=None, title="Гарри Поттер и философский камень", lang="en", description="Первая книга о юном волшебнике",
            publisher="Bloomsbury", pub_date=datetime(1997, 6, 26), subjects="Фэнтези, приключения", series="Гарри Поттер"),
    BookDto(authors="Лев Толстой", book_id=7, cover_path=None, title="Война и мир", lang="ru", description="Эпопея о войне 1812 года",
            publisher="Русский вестник", pub_date=datetime(1869, 1, 1), subjects="Исторический роман, классика", series=None),
    BookDto(authors="Пауло Коэльо", book_id=8, cover_path=None, title="Алхимик", lang="pt", description="Притча о поиске своего предназначения",
            publisher="Editora Rocco", pub_date=datetime(1988, 1, 1), subjects="Философия, притча", series=None),
    BookDto(authors="Габриэль Гарсиа Маркес", book_id=9, cover_path=None, title="Сто лет одиночества", lang="es", description="Сага о семье Буэндиа",
            publisher="Editorial Sudamericana", pub_date=datetime(1967, 5, 30), subjects="Магический реализм, семейная сага", series=None)
]


@router.get("/all")
def get_all_books(limit: int | None, offset: int = 0) -> list[BookCardDto]:
    if limit is None:
        books = mocked_books[offset:]
    else:
        books = mocked_books[offset: offset + limit]
    return [BookCardDto(book_id=book.book_id, title=book.title, cover_path=book.cover_path, authors=book.authors) for book in books]


@router.get("/{book_id}")
def get_book_by_id(book_id: int) -> BookDto:
    if book_id > len(mocked_books) or book_id < 0:
        raise HTTPException(404, "Book not found!")
    return mocked_books[book_id]
