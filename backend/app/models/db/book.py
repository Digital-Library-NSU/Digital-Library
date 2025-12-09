from typing import Optional
import datetime

from sqlalchemy import ARRAY, BigInteger, Boolean, Date, DateTime, ForeignKeyConstraint, Index, Integer, PrimaryKeyConstraint, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Author(Base):
    __tablename__ = 'authors'
    __table_args__ = (
        PrimaryKeyConstraint('id', name='authors_pkey'),
        UniqueConstraint('name', name='authors_name_key')
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    sort_name: Mapped[Optional[str]] = mapped_column(Text)

    book_authors: Mapped[list['BookAuthor']] = relationship(
        'BookAuthor', back_populates='author')


class Book(Base):
    __tablename__ = 'books'
    __table_args__ = (
        PrimaryKeyConstraint('id', name='books_pkey'),
        Index('idx_books_subjects', 'subjects'),
        Index('idx_books_title')
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    sort_title: Mapped[Optional[str]] = mapped_column(Text)
    lang: Mapped[Optional[str]] = mapped_column(Text)
    description: Mapped[Optional[str]] = mapped_column(Text)
    publisher: Mapped[Optional[str]] = mapped_column(Text)
    pub_date: Mapped[Optional[datetime.date]] = mapped_column(Date)
    subjects: Mapped[Optional[list[str]]] = mapped_column(ARRAY(Text()))
    series: Mapped[Optional[str]] = mapped_column(Text)
    meta: Mapped[Optional[dict]] = mapped_column(JSONB)

    book_authors: Mapped[list['BookAuthor']] = relationship(
        'BookAuthor', back_populates='book')
    book_identifiers: Mapped[list['BookIdentifier']] = relationship(
        'BookIdentifier', back_populates='book')
    editions: Mapped[list['Edition']] = relationship(
        'Edition', back_populates='book')
    content_paragraphs: Mapped[list['ContentParagraph']] = relationship(
        'ContentParagraph', back_populates='book')


class BookAuthor(Base):
    __tablename__ = 'book_authors'
    __table_args__ = (
        ForeignKeyConstraint(['author_id'], ['authors.id'],
                             ondelete='CASCADE', name='book_authors_author_id_fkey'),
        ForeignKeyConstraint(['book_id'], ['books.id'],
                             ondelete='CASCADE', name='book_authors_book_id_fkey'),
        PrimaryKeyConstraint('book_id', 'author_id', name='book_authors_pkey')
    )

    book_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    author_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    role: Mapped[Optional[str]] = mapped_column(Text)
    ord: Mapped[Optional[int]] = mapped_column(Integer)

    author: Mapped['Author'] = relationship(
        'Author', back_populates='book_authors')
    book: Mapped['Book'] = relationship('Book', back_populates='book_authors')


class BookIdentifier(Base):
    __tablename__ = 'book_identifiers'
    __table_args__ = (
        ForeignKeyConstraint(['book_id'], [
                             'books.id'], ondelete='CASCADE', name='book_identifiers_book_id_fkey'),
        PrimaryKeyConstraint('book_id', 'scheme', 'value',
                             name='book_identifiers_pkey'),
        UniqueConstraint('scheme', 'value',
                         name='book_identifiers_scheme_value_key')
    )

    book_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    scheme: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[str] = mapped_column(Text, primary_key=True)

    book: Mapped['Book'] = relationship(
        'Book', back_populates='book_identifiers')


class Edition(Base):
    __tablename__ = 'editions'
    __table_args__ = (
        ForeignKeyConstraint(['book_id'], ['books.id'],
                             ondelete='CASCADE', name='editions_book_id_fkey'),
        PrimaryKeyConstraint('id', name='editions_pkey'),
        UniqueConstraint('sha256', name='editions_sha256_key'),
        Index('idx_editions_book', 'book_id')
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    format: Mapped[str] = mapped_column(Text, nullable=False)
    storage_key: Mapped[str] = mapped_column(Text, nullable=False)
    book_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    size_bytes: Mapped[Optional[int]] = mapped_column(BigInteger)
    sha256: Mapped[Optional[str]] = mapped_column(Text)
    drm: Mapped[Optional[bool]] = mapped_column(Boolean)
    opf_path: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(True), server_default=text('now()'))

    book: Mapped[Optional['Book']] = relationship(
        'Book', back_populates='editions')
    edition_chapters: Mapped[list['EditionChapter']] = relationship(
        'EditionChapter', back_populates='edition')
    content_paragraphs: Mapped[list['ContentParagraph']] = relationship(
        'ContentParagraph', back_populates='edition')


class EditionChapter(Base):
    __tablename__ = 'edition_chapters'
    __table_args__ = (
        ForeignKeyConstraint(['edition_id'], [
                             'editions.id'], ondelete='CASCADE', name='edition_chapters_edition_id_fkey'),
        PrimaryKeyConstraint('id', name='edition_chapters_pkey'),
        Index('idx_chapters_ed', 'edition_id', 'ord')
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    ord: Mapped[int] = mapped_column(Integer, nullable=False)
    edition_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    title: Mapped[Optional[str]] = mapped_column(Text)
    href: Mapped[Optional[str]] = mapped_column(Text)

    edition: Mapped[Optional['Edition']] = relationship(
        'Edition', back_populates='edition_chapters')
    content_paragraphs: Mapped[list['ContentParagraph']] = relationship(
        'ContentParagraph', back_populates='chapter')


class ContentParagraph(Base):
    __tablename__ = 'content_paragraphs'
    __table_args__ = (
        ForeignKeyConstraint(['book_id'], [
                             'books.id'], ondelete='CASCADE', name='content_paragraphs_book_id_fkey'),
        ForeignKeyConstraint(['chapter_id'], ['edition_chapters.id'],
                             ondelete='SET NULL', name='content_paragraphs_chapter_id_fkey'),
        ForeignKeyConstraint(['edition_id'], [
                             'editions.id'], ondelete='CASCADE', name='content_paragraphs_edition_id_fkey'),
        PrimaryKeyConstraint('id', name='content_paragraphs_pkey'),
        UniqueConstraint('es_doc_id', name='content_paragraphs_es_doc_id_key'),
        Index('idx_paragraphs_book_start', 'book_id', 'para_start')
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    para_start: Mapped[int] = mapped_column(Integer, nullable=False)
    para_end: Mapped[int] = mapped_column(Integer, nullable=False)
    window_size: Mapped[int] = mapped_column(Integer, nullable=False)
    book_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    edition_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    chapter_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    tokens_from: Mapped[Optional[int]] = mapped_column(Integer)
    tokens_to: Mapped[Optional[int]] = mapped_column(Integer)
    es_index: Mapped[Optional[str]] = mapped_column(Text)
    es_doc_id: Mapped[Optional[str]] = mapped_column(Text)
    lang: Mapped[Optional[str]] = mapped_column(Text)
    para_type: Mapped[Optional[str]] = mapped_column(Text)
    is_heading: Mapped[Optional[bool]] = mapped_column(Boolean)

    book: Mapped[Optional['Book']] = relationship(
        'Book', back_populates='content_paragraphs')
    chapter: Mapped[Optional['EditionChapter']] = relationship(
        'EditionChapter', back_populates='content_paragraphs')
    edition: Mapped[Optional['Edition']] = relationship(
        'Edition', back_populates='content_paragraphs')
