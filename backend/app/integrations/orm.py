from typing import Optional
import datetime
import uuid

from sqlalchemy import (
    ARRAY,
    BigInteger,
    Date,
    DateTime,
    Enum,
    ForeignKeyConstraint,
    Index,
    Integer,
    PrimaryKeyConstraint,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
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

    chapters: Mapped[list['Chapter']] = relationship(
        'Chapter',
        back_populates='book',
    )
    content_paragraphs: Mapped[list['ContentParagraph']] = relationship(
        'ContentParagraph',
        back_populates='book',
    )


class User(Base):
    __tablename__ = 'users'
    __table_args__ = (
        PrimaryKeyConstraint('id', name='users_pkey'),
        UniqueConstraint('login', name='users_login_key'),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        server_default=text('gen_random_uuid()'),
    )
    login: Mapped[str] = mapped_column(String(255), nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(60), nullable=False)
    role: Mapped[str] = mapped_column(
        Enum('user', 'admin', name='user_role'),
        nullable=False,
        server_default=text("'user'::user_role"),
    )

    sessions: Mapped[list['Session']] = relationship(
        'Session',
        back_populates='user',
    )


class Chapter(Base):
    __tablename__ = 'chapters'
    __table_args__ = (
        ForeignKeyConstraint(
            ['book_id'],
            ['books.id'],
            ondelete='CASCADE',
            name='chapters_book_id_fkey',
        ),
        PrimaryKeyConstraint('id', name='chapters_pkey'),
        UniqueConstraint('book_id', 'ord', name='chapters_book_id_ord_key'),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    book_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    ord: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[Optional[str]] = mapped_column(Text)

    book: Mapped[Optional['Book']] = relationship(
        'Book',
        back_populates='chapters',
    )
    content_paragraphs: Mapped[list['ContentParagraph']] = relationship(
        'ContentParagraph',
        back_populates='chapter',
    )


class Session(Base):
    __tablename__ = 'sessions'
    __table_args__ = (
        ForeignKeyConstraint(
            ['user_id'],
            ['users.id'],
            name='sessions_user_id_fkey',
        ),
        PrimaryKeyConstraint('id', name='sessions_pkey'),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        server_default=text('gen_random_uuid()'),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    created_time: Mapped[datetime.datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=text('now()'),
    )

    user: Mapped['User'] = relationship(
        'User',
        back_populates='sessions',
    )


class ContentParagraph(Base):
    __tablename__ = 'content_paragraphs'
    __table_args__ = (
        ForeignKeyConstraint(
            ['book_id'],
            ['books.id'],
            ondelete='CASCADE',
            name='content_paragraphs_book_id_fkey',
        ),
        ForeignKeyConstraint(
            ['chapter_id'],
            ['chapters.id'],
            ondelete='SET NULL',
            name='content_paragraphs_chapter_id_fkey',
        ),
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

    book: Mapped[Optional['Book']] = relationship(
        'Book',
        back_populates='content_paragraphs',
    )
    chapter: Mapped[Optional['Chapter']] = relationship(
        'Chapter',
        back_populates='content_paragraphs',
    )