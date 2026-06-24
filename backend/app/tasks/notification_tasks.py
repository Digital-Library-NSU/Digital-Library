from app.celery_app import celery_app


print("[INFO] Notification tasks loaded without embedding model preload")


@celery_app.task(name="notifications.ping")
def notification_ping() -> str:
    return "ok"
