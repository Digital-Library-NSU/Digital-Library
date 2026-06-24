from celery import Celery

from app.config import CELERY_BROKER_URL, CELERY_RESULT_BACKEND


celery_app = Celery(
    "library_backend",
    broker=CELERY_BROKER_URL,
    backend=CELERY_RESULT_BACKEND,
    include=[
        "app.tasks.import_tasks",
        "app.tasks.notification_tasks",
    ],
)

celery_app.conf.update(
    task_track_started=True,
    worker_proc_alive_timeout=240,
    task_routes={
        "books.import_epub": {"queue": "imports"},
        "notifications.*": {"queue": "notifications"},
    },
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
)
