from celery import Celery
from celery.schedules import crontab

from app.config import settings

celery_app = Celery(
    "human_capital_exchange",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.tasks.settlement"],
)

celery_app.conf.timezone = "UTC"
celery_app.conf.beat_schedule = {
    # Runs daily at 06:00 UTC: expire contracts, generate placeholder reports,
    # and mark any that have passed their due_date as OVERDUE.
    "daily-settlement-scan": {
        "task": "app.tasks.settlement.daily_settlement_scan",
        "schedule": crontab(hour=6, minute=0),
    },
}
