from argparse import Namespace
from pathlib import Path
from typing import Any, Dict

from app.celery_app import celery_app
from app.config import (
    PG_DSN,
    ES_URL,
    IDX_META,
    IDX_CONTENT,
    EMBED_MODEL,
    EMBED_DEVICE,
    EMBED_NORMALIZE,
    MAX_MISSING_SPINE,
)
from app.import_epub import process_epub


def _build_import_args() -> Namespace:
    return Namespace(
        # Postgres
        dsn=PG_DSN,
        root="---",
        create_db=False,
        recreate_schema=False,

        # Elasticsearch
        no_es=False,
        es_url=ES_URL,
        es_index_meta=IDX_META,
        es_index_content=IDX_CONTENT,
        recreate_es=False,
        es_no_source=False,
        es_use_templates=True,
        es_dense_vector_dim=1024,
        es_enable_suggest=False,

        # абзацы/окна
        min_paragraph_words=15,
        no_join_short_paragraphs=False,
        para_window_size=2,
        para_window_stride=1,

        # битые EPUB
        max_missing_spine=MAX_MISSING_SPINE,
        warn_cap=5,

        # embeddings
        embed_model=EMBED_MODEL,
        embed_device=EMBED_DEVICE,
        embed_batch_size=64,
        embed_max_words=256,
        embed_overlap_words=32,
        no_embed_normalize=not EMBED_NORMALIZE,

        limit=0,

        export_root=None,
    )


@celery_app.task(bind=True, name="books.import_epub")
def import_epub_task(self, tmp_path: str, original_filename: str) -> Dict[str, Any]:
    path = Path(tmp_path)

    if not path.exists():
        raise FileNotFoundError(f"Uploaded EPUB file not found: {tmp_path}")

    try:
        self.update_state(
            state="STARTED",
            meta={
                "filename": original_filename,
                "stage": "processing",
            },
        )

        status = process_epub(
            file_path=path,
            args=_build_import_args(),
        )

        return {
            "status": status,
            "filename": original_filename,
        }

    finally:
        try:
            path.unlink(missing_ok=True)
        except Exception:
            pass