CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS books (
  id                    BIGSERIAL PRIMARY KEY,
  title                 TEXT NOT NULL,
  authors               TEXT[],
  lang                  TEXT,
  description           TEXT,
  publisher             TEXT,
  pub_date              DATE,
  subjects              TEXT[],
  series                TEXT,
  total_blocks_count    INT NOT NULL
);

CREATE TABLE IF NOT EXISTS chapters (
  id            BIGSERIAL PRIMARY KEY,
  book_id       BIGINT REFERENCES books(id) ON DELETE CASCADE,
  ord           INT NOT NULL,
  title         TEXT,
  blocks_count  INT NOT NULL,
  UNIQUE (book_id, ord)
);

CREATE TABLE IF NOT EXISTS content_paragraphs (
  id          BIGSERIAL PRIMARY KEY,
  book_id     BIGINT REFERENCES books(id) ON DELETE CASCADE,
  chapter_id  BIGINT REFERENCES chapters(id) ON DELETE SET NULL,
  block_start INT NOT NULL,
  block_end   INT NOT NULL,
  tokens_from INT,
  tokens_to   INT,
  es_doc_id   TEXT UNIQUE,
  lang        TEXT,
  para_type   TEXT
);

CREATE INDEX IF NOT EXISTS idx_paragraphs_chapter_block
ON content_paragraphs (chapter_id, block_start, id);

CREATE TABLE IF NOT EXISTS content_blocks (
  book_id      BIGINT NOT NULL REFERENCES books(id) ON DELETE CASCADE,
  chapter_id   BIGINT NOT NULL REFERENCES chapters(id) ON DELETE CASCADE,
  block_index  INT NOT NULL,
  char_start   BIGINT NOT NULL,
  char_end     BIGINT NOT NULL,
  char_count   INT NOT NULL,
  PRIMARY KEY (book_id, chapter_id, block_index),
  CHECK (char_start >= 0),
  CHECK (char_end >= char_start),
  CHECK (char_count >= 0)
);

CREATE INDEX IF NOT EXISTS idx_content_blocks_chapter_offset
ON content_blocks (chapter_id, char_start);

-- === Users/Auth ===

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'user_role') THEN
        CREATE TYPE user_role AS ENUM('user', 'admin');
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS users (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    login           VARCHAR(255) NOT NULL UNIQUE,
    hashed_password VARCHAR(60) NOT NULL,
    role            user_role DEFAULT 'user' NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID REFERENCES users(id) NOT NULL,
    created_time    TIMESTAMP DEFAULT now() NOT NULL
);

CREATE TABLE IF NOT EXISTS reviews (
    id              BIGSERIAL PRIMARY KEY,
    user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    book_id         BIGINT NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    rating          INT NOT NULL CHECK (rating BETWEEN 1 AND 10),
    review_text     TEXT NOT NULL,
    created_at      TIMESTAMP NOT NULL DEFAULT now(),
    updated_at      TIMESTAMP,
    UNIQUE (user_id, book_id)
);

CREATE INDEX IF NOT EXISTS idx_reviews_book_id ON reviews(book_id);

CREATE INDEX IF NOT EXISTS idx_reviews_user_id ON reviews(user_id);

--- ===

CREATE TABLE IF NOT EXISTS bookmarks (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id            UUID REFERENCES users(id) ON DELETE CASCADE NOT NULL,
    book_id             BIGINT REFERENCES books(id) ON DELETE CASCADE NOT NULL,
    chapter_id          BIGINT REFERENCES chapters(id) NOT NULL,
    data_block_index    INT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS bookmarks_owner_book_chapter_block_key
ON bookmarks (owner_id, book_id, chapter_id, data_block_index);

CREATE INDEX IF NOT EXISTS idx_bookmarks_owner_book
ON bookmarks (owner_id, book_id);
--- ===

CREATE TABLE IF NOT EXISTS reading_progress (
    user_id                 UUID REFERENCES users(id) ON DELETE CASCADE NOT NULL,
    book_id                 BIGINT REFERENCES books(id) ON DELETE CASCADE NOT NULL,
    curr_chapter_id         BIGINT REFERENCES chapters(id) NOT NULL,
    curr_data_block_index   INT NOT NULL,
    curr_block_char_offset  INT NOT NULL DEFAULT 0,
    chapter_scroll_ratio    DOUBLE PRECISION NOT NULL DEFAULT 0,
    progress                INT NOT NULL CHECK (progress BETWEEN 0 AND 100),
    CHECK (curr_block_char_offset >= 0),
    CHECK (chapter_scroll_ratio >= 0 AND chapter_scroll_ratio <= 1),
    UNIQUE (user_id, book_id)
);
