from typing import Optional
import datetime

from sqlalchemy import ARRAY, BigInteger, Date, ForeignKeyConstraint, Index, Integer, PrimaryKeyConstraint, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Book(Base):
    __tablename__ = 'books'
    __table_args__ = (
        PrimaryKeyConstraint('id', name='books_pkey'),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    authors: Mapped[Optional[list[str]]] = mapped_column(ARRAY(Text()))
    lang: Mapped[Optional[str]] = mapped_column(Text)
    description: Mapped[Optional[str]] = mapped_column(Text)
    publisher: Mapped[Optional[str]] = mapped_column(Text)
    pub_date: Mapped[Optional[datetime.date]] = mapped_column(Date)
    subjects: Mapped[Optional[list[str]]] = mapped_column(ARRAY(Text()))
    series: Mapped[Optional[str]] = mapped_column(Text)

    chapters: Mapped[list['Chapter']] = relationship('Chapter', back_populates='book')
    content_paragraphs: Mapped[list['ContentParagraph']] = relationship('ContentParagraph', back_populates='book')


class Chapter(Base):
    __tablename__ = 'chapters'
    __table_args__ = (
        ForeignKeyConstraint(['book_id'], ['books.id'], ondelete='CASCADE', name='chapters_book_id_fkey'),
        PrimaryKeyConstraint('id', name='chapters_pkey'),
        UniqueConstraint('book_id', 'ord', name='chapters_book_id_ord_key'),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    book_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    ord: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[Optional[str]] = mapped_column(Text)

    book: Mapped[Optional['Book']] = relationship('Book', back_populates='chapters')
    content_paragraphs: Mapped[list['ContentParagraph']] = relationship('ContentParagraph', back_populates='chapter')


class ContentParagraph(Base):
    __tablename__ = 'content_paragraphs'
    __table_args__ = (
        ForeignKeyConstraint(['book_id'], ['books.id'], ondelete='CASCADE', name='content_paragraphs_book_id_fkey'),
        ForeignKeyConstraint(['chapter_id'], ['chapters.id'], ondelete='SET NULL', name='content_paragraphs_chapter_id_fkey'),
        PrimaryKeyConstraint('id', name='content_paragraphs_pkey'),
        UniqueConstraint('es_doc_id', name='content_paragraphs_es_doc_id_key'),
        Index('idx_paragraphs_chapter_block', 'chapter_id', 'block_start', 'id'),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    book_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    chapter_id: Mapped[Optional[int]] = mapped_column(BigInteger)

    block_start: Mapped[int] = mapped_column(Integer, nullable=False)
    block_end: Mapped[int] = mapped_column(Integer, nullable=False)

    tokens_from: Mapped[Optional[int]] = mapped_column(Integer)
    tokens_to: Mapped[Optional[int]] = mapped_column(Integer)
    es_doc_id: Mapped[Optional[str]] = mapped_column(Text)
    lang: Mapped[Optional[str]] = mapped_column(Text)
    para_type: Mapped[Optional[str]] = mapped_column(Text)

    book: Mapped[Optional['Book']] = relationship('Book', back_populates='content_paragraphs')
    chapter: Mapped[Optional['Chapter']] = relationship('Chapter', back_populates='content_paragraphs')