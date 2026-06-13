import os
from celery import Celery
from app.config import settings

# Initialize Celery app
celery_app = Celery(
    "dse_meli_tasks",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND
)

# Configuration settings
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="America/Sao_Paulo",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=300,  # 5 minutes max per task
)

# Autodiscover tasks from the app/tasks directory
celery_app.autodiscover_tasks(["app.tasks"])
