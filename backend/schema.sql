-- === Books ===

CREATE TABLE IF NOT EXISTS authors (
  id        BIGSERIAL PRIMARY KEY,
  name      TEXT NOT NULL UNIQUE,
  sort_name TEXT
);

CREATE TABLE IF NOT EXISTS books (
  id          BIGSERIAL PRIMARY KEY,
  title       TEXT NOT NULL,
  sort_title  TEXT,
  lang        TEXT,
  description TEXT,
  publisher   TEXT,
  pub_date    DATE,
  subjects    TEXT[],
  series      TEXT,
  meta        JSONB
);

CREATE TABLE IF NOT EXISTS book_authors (
  book_id   BIGINT REFERENCES books(id) ON DELETE CASCADE,
  author_id BIGINT REFERENCES authors(id) ON DELETE CASCADE,
  role      TEXT,
  ord       INT,
  PRIMARY KEY (book_id, author_id)
);

CREATE TABLE IF NOT EXISTS book_identifiers (
  book_id BIGINT REFERENCES books(id) ON DELETE CASCADE,
  scheme  TEXT NOT NULL,
  value   TEXT NOT NULL,
  PRIMARY KEY (book_id, scheme, value),
  UNIQUE (scheme, value)
);

CREATE TABLE IF NOT EXISTS editions (
  id          BIGSERIAL PRIMARY KEY,
  book_id     BIGINT REFERENCES books(id) ON DELETE CASCADE,
  format      TEXT NOT NULL,
  storage_key TEXT NOT NULL,
  size_bytes  BIGINT,
  sha256      TEXT UNIQUE,
  drm         BOOLEAN,
  opf_path    TEXT,
  created_at  TIMESTAMPTZ DEFAULT now()
);

-- Оглавление/главы
CREATE TABLE IF NOT EXISTS edition_chapters (
  id          BIGSERIAL PRIMARY KEY,
  edition_id  BIGINT REFERENCES editions(id) ON DELETE CASCADE,
  ord         INT NOT NULL,
  title       TEXT,
  href        TEXT
);

-- Метаданные АБЗАЦЕВ/окон
CREATE TABLE IF NOT EXISTS content_paragraphs (
  id           BIGSERIAL PRIMARY KEY,
  book_id      BIGINT REFERENCES books(id) ON DELETE CASCADE,
  edition_id   BIGINT REFERENCES editions(id) ON DELETE CASCADE,
  chapter_id   BIGINT REFERENCES edition_chapters(id) ON DELETE SET NULL,
  para_start   INT NOT NULL,
  para_end     INT NOT NULL,
  window_size  INT NOT NULL,
  tokens_from  INT,
  tokens_to    INT,
  es_index     TEXT,
  es_doc_id    TEXT UNIQUE,
  lang         TEXT,
  para_type    TEXT,
  is_heading   BOOLEAN
);

CREATE INDEX IF NOT EXISTS idx_books_title ON books USING GIN (to_tsvector('simple', coalesce(title,'')));
CREATE INDEX IF NOT EXISTS idx_books_subjects ON books USING GIN (subjects);
CREATE INDEX IF NOT EXISTS idx_editions_book ON editions (book_id);
CREATE INDEX IF NOT EXISTS idx_chapters_ed ON edition_chapters (edition_id, ord);
CREATE INDEX IF NOT EXISTS idx_paragraphs_book_start ON content_paragraphs (book_id, para_start);

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
