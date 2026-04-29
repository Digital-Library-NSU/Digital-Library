CREATE TABLE IF NOT EXISTS books (
  id          BIGSERIAL PRIMARY KEY,
  title       TEXT NOT NULL,
  authors     TEXT[],
  lang        TEXT,
  description TEXT,
  publisher   TEXT,
  pub_date    DATE,
  subjects    TEXT[],
  series      TEXT
);

CREATE TABLE IF NOT EXISTS chapters (
  id      BIGSERIAL PRIMARY KEY,
  book_id BIGINT REFERENCES books(id) ON DELETE CASCADE,
  ord     INT NOT NULL,
  title   TEXT,
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

-- === Users ===

CREATE TYPE user_role AS ENUM('user', 'admin');

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