from argparse import Namespace
from datetime import datetime, timezone
import os
from pathlib import Path
import time
from typing import Any, Dict

from celery.signals import worker_process_init

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
from app.import_epub.importer import (
    clear_encoder_cache,
    get_encoder,
    get_encoder_dim,
    is_encoder_cached,
)

try:
    import torch
except Exception:
    torch = None


IMPORT_WORKER_ROLE = "import"
CUDA_PRELOAD_REQUIRED_FREE_GB = 6.0
CUDA_PRELOAD_WAIT_TIMEOUT_SECONDS = 180
CUDA_PRELOAD_WAIT_INTERVAL_SECONDS = 5


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
        embed_batch_size=16,
        embed_max_words=256,
        embed_overlap_words=32,
        no_embed_normalize=not EMBED_NORMALIZE,

        limit=0,

        export_root=None,
    )


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_import_worker() -> bool:
    return os.getenv("CELERY_WORKER_ROLE") == IMPORT_WORKER_ROLE


def _should_wait_for_cuda_memory() -> bool:
    if torch is None or not torch.cuda.is_available():
        return False

    return EMBED_DEVICE in ("auto", "cuda")


def _wait_for_cuda_memory() -> None:
    if not _should_wait_for_cuda_memory():
        return

    deadline = time.monotonic() + CUDA_PRELOAD_WAIT_TIMEOUT_SECONDS

    while True:
        free_bytes, total_bytes = torch.cuda.mem_get_info()
        free_gb = free_bytes / 1024 ** 3
        total_gb = total_bytes / 1024 ** 3

        if free_gb >= CUDA_PRELOAD_REQUIRED_FREE_GB:
            print(
                f"[INFO] CUDA memory ready for import model preload: "
                f"{free_gb:.2f}/{total_gb:.2f} GiB free"
            )
            return

        if time.monotonic() >= deadline:
            raise RuntimeError(
                "CUDA memory did not become available for import model preload: "
                f"{free_gb:.2f}/{total_gb:.2f} GiB free, "
                f"required {CUDA_PRELOAD_REQUIRED_FREE_GB:.2f} GiB"
            )

        print(
            f"[INFO] Waiting for CUDA memory before import model preload: "
            f"{free_gb:.2f}/{total_gb:.2f} GiB free, "
            f"required {CUDA_PRELOAD_REQUIRED_FREE_GB:.2f} GiB"
        )
        time.sleep(CUDA_PRELOAD_WAIT_INTERVAL_SECONDS)


def _preload_import_encoder() -> None:
    if not EMBED_MODEL:
        return

    if not is_encoder_cached(EMBED_MODEL, EMBED_DEVICE):
        _wait_for_cuda_memory()

    enc, device = get_encoder(EMBED_MODEL, device_mode=EMBED_DEVICE)
    get_encoder_dim(EMBED_MODEL, device)
    print(
        f"[INFO] Import worker embedding model ready: "
        f"model={EMBED_MODEL}, device={device}"
    )


@worker_process_init.connect
def warm_import_encoder(**_kwargs) -> None:
    if _is_import_worker():
        _preload_import_encoder()
    else:
        print("[INFO] Celery worker started without embedding model preload")


@celery_app.task(bind=True, name="books.import_epub")
def import_epub_task(self, tmp_path: str, original_filename: str) -> Dict[str, Any]:
    path = Path(tmp_path)

    if not path.exists():
        raise FileNotFoundError(f"Uploaded EPUB file not found: {tmp_path}")

    task_started_at = _utc_now_iso()

    def report_progress(payload: Dict[str, Any]) -> None:
        stage = str(payload.get("stage") or "processing")
        current = payload.get("current")
        total = payload.get("total")

        meta = {
            "filename": original_filename,
            "stage": stage,
            "status_label": payload.get("status_label") or "Импортируем книгу",
            "title": payload.get("title"),
            "authors": payload.get("authors"),
            "progress_percent": payload.get("progress_percent"),
            "current": current,
            "total": total,
            "unit": payload.get("unit"),
            "queued": False,
            "started_at": task_started_at,
            "updated_at": _utc_now_iso(),
        }
        self.update_state(state="PROGRESS", meta=meta)

    try:
        self.update_state(
            state="STARTED",
            meta={
                "filename": original_filename,
                "stage": "processing",
                "status_label": "Начинаем импорт",
                "progress_percent": 0.0,
                "queued": False,
                "started_at": task_started_at,
                "updated_at": _utc_now_iso(),
            },
        )
        self.update_state(
            state="PROGRESS",
            meta={
                "filename": original_filename,
                "stage": "loading_model",
                "status_label": "Поднимаем модель векторизации",
                "progress_percent": None,
                "queued": False,
                "started_at": task_started_at,
                "updated_at": _utc_now_iso(),
            },
        )
        _preload_import_encoder()

        status = process_epub(
            file_path=path,
            args=_build_import_args(),
            progress_callback=report_progress,
        )

        if status == "skipped":
            raise ValueError("Битый EPUB: не удалось разобрать структуру книги")

        if isinstance(status, dict):
            status_value = status.get("status")
            if isinstance(status_value, str) and status_value.startswith("skipped"):
                raise ValueError("Битый EPUB: книга не содержит пригодного контента")

        return {
            "status": status,
            "filename": original_filename,
            "title": status.get("title") if isinstance(status, dict) else None,
            "authors": status.get("authors") if isinstance(status, dict) else None,
            "stage": "completed",
            "status_label": "Загрузка завершена",
            "progress_percent": 100.0,
            "queued": False,
            "started_at": task_started_at,
            "updated_at": _utc_now_iso(),
        }

    except Exception as exc:
        if torch is not None and isinstance(exc, torch.OutOfMemoryError):
            clear_encoder_cache()
            self.update_state(
                state="PROGRESS",
                meta={
                    "filename": original_filename,
                    "stage": "failed",
                    "status_label": "Out of Memory: GPU",
                    "progress_percent": None,
                    "queued": False,
                    "started_at": task_started_at,
                    "updated_at": _utc_now_iso(),
                    "error": (
                        "Видеопамяти не хватило для векторизации этой книги. "
                        "Попробуйте уменьшить batch импорта или загрузить книгу на CPU."
                    ),
                },
            )
            print("[ERROR] CUDA OOM during import; stopping worker child process")
            os._exit(1)
        raise

    finally:
        try:
            path.unlink(missing_ok=True)
        except Exception:
            pass
