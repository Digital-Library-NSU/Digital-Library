from fastapi import APIRouter, HTTPException

from app.models.dtos import BookCardDto, BookDto
from datetime import datetime

router = APIRouter(prefix="/books")


mocked_bookcards = {
    0: BookCardDto(book_id=0, title="Кровь, пот и пиксели", cover_path=None, authors="Джейсон Шрейер"),
    1: BookCardDto(book_id=1, title="Ионыч", cover_path=None, authors="Антон Чехов"),
    2: BookCardDto(book_id=2, title="Мастер и Маргарита", cover_path=None, authors="Михаил Булгаков"),
    3: BookCardDto(book_id=3, title="1984", cover_path=None, authors="Джордж Оруэлл"),
    4: BookCardDto(book_id=4, title="Маленький принц", cover_path=None, authors="Антуан де Сент-Экзюпери"),
    5: BookCardDto(book_id=5, title="Преступление и наказание", cover_path=None, authors="Фёдор Достоевский"),
    6: BookCardDto(book_id=6, title="Гарри Поттер и философский камень", cover_path=None, authors="Джоан Роулинг"),
    7: BookCardDto(book_id=7, title="Война и мир", cover_path=None, authors="Лев Толстой"),
    8: BookCardDto(book_id=8, title="Алхимик", cover_path=None, authors="Пауло Коэльо"),
    9: BookCardDto(book_id=9, title="Сто лет одиночества", cover_path=None, authors="Габриэль Гарсиа Маркес")
}


mocked_books = {
    0: BookDto(book_id=0, cover_path=None, title="Кровь, пот и пиксели", lang="ru", description="Закулисные истории создания видеоигр", publisher="Манн, Иванов и Фербер", pub_date=datetime(2018, 1, 1), subjects="Игровая индустрия, разработка", series=None),
    1: BookDto(book_id=1, cover_path=None, title="Ионыч", lang="ru", description="История духовной деградации земского врача", publisher="Разные издания", pub_date=datetime(1898, 1, 1), subjects="Русская классика, проза", series=None),
    2: BookDto(book_id=2, cover_path=None, title="Мастер и Маргарита", lang="ru", description="Философский роман о добре и зле", publisher="Художественная литература", pub_date=datetime(1966, 1, 1), subjects="Фантастика, философия", series=None),
    3: BookDto(book_id=3, cover_path=None, title="1984", lang="en", description="Антиутопия о тоталитарном обществе", publisher="Secker & Warburg", pub_date=datetime(1949, 6, 8), subjects="Антиутопия, политика", series=None),
    4: BookDto(book_id=4, cover_path=None, title="Маленький принц", lang="fr", description="Философская сказка-притча", publisher="Reynal & Hitchcock", pub_date=datetime(1943, 4, 6), subjects="Философия, сказка", series=None),
    5: BookDto(book_id=5, cover_path=None, title="Преступление и наказание", lang="ru", description="Роман о моральных терзаниях убийцы", publisher="Русский вестник", pub_date=datetime(1866, 1, 1), subjects="Психология, философия", series=None),
    6: BookDto(book_id=6, cover_path=None, title="Гарри Поттер и философский камень", lang="en", description="Первая книга о юном волшебнике", publisher="Bloomsbury", pub_date=datetime(1997, 6, 26), subjects="Фэнтези, приключения", series="Гарри Поттер"),
    7: BookDto(book_id=7, cover_path=None, title="Война и мир", lang="ru", description="Эпопея о войне 1812 года", publisher="Русский вестник", pub_date=datetime(1869, 1, 1), subjects="Исторический роман, классика", series=None),
    8: BookDto(book_id=8, cover_path=None, title="Алхимик", lang="pt", description="Притча о поиске своего предназначения", publisher="Editora Rocco", pub_date=datetime(1988, 1, 1), subjects="Философия, притча", series=None),
    9: BookDto(book_id=9, cover_path=None, title="Сто лет одиночества", lang="es", description="Сага о семье Буэндиа", publisher="Editorial Sudamericana", pub_date=datetime(1967, 5, 30), subjects="Магический реализм, семейная сага", series=None)
}


@router.get("/all")
def get_all_books() -> list[BookCardDto]:
    return [value for value in mocked_bookcards.values()]


@router.get("/{book_id}")
def get_book_by_id(book_id: int) -> BookDto:
    if book_id not in mocked_books.keys():
        raise HTTPException(404, "Book not found!")
    return mocked_books[book_id]
