from celery import Celery

from llm_security_platform.app.config import CELERY_TASK_ALWAYS_EAGER, REDIS_URL


celery_app = Celery("llm_security_platform", broker=REDIS_URL, backend=REDIS_URL)
celery_app.conf.update(
    accept_content=["json"],
    result_serializer="json",
    task_always_eager=CELERY_TASK_ALWAYS_EAGER,
    task_eager_propagates=True,
    task_serializer="json",
    task_track_started=True,
    timezone="UTC",
)
