"""
Celery tasks for the settlement engine.

Run the worker:
    celery -A app.celery_app.celery_app worker --loglevel=info

Run the beat scheduler (triggers daily-settlement-scan):
    celery -A app.celery_app.celery_app beat --loglevel=info
"""
from app.celery_app import celery_app


@celery_app.task(bind=True, max_retries=3, default_retry_delay=300)
def daily_settlement_scan(self):
    """
    Runs daily at 06:00 UTC (configured in celery_app.beat_schedule).

    1. Expire contracts whose end_date has passed.
    2. Create PENDING placeholder IncomeReport records for completed quarters.
    3. Mark PENDING placeholders past their due_date as OVERDUE and apply
       reputation penalties to the issuers.
    """
    from app.database import SessionLocal
    from app.services.contract_service import expire_overdue
    from app.services.settlement_service import generate_expected_reports, mark_overdue_reports

    db = SessionLocal()
    try:
        expire_overdue(db)
        generate_expected_reports(db)
        mark_overdue_reports(db)
        from app.services.reputation_service import detect_and_apply_defaults
        detect_and_apply_defaults(db)
    except Exception as exc:
        db.rollback()
        raise self.retry(exc=exc)
    finally:
        db.close()
