"""
Reputation engine — penalty/bonus application and default detection.

Score semantics
---------------
  100   = pristine record (starting value)
  0     = permanently barred in practice (no formal floor enforcement needed)

Events are append-only.  Penalties and bonuses directly mutate
User.reputation_score; positive adjustments (on_time_report_bonus) are
applied silently without creating an event record.

Default detection
-----------------
After the daily mark_overdue_reports() run, detect_and_apply_defaults()
inspects every ACTIVE contract for a streak of consecutive OVERDUE reports.
A streak ≥ default_consecutive_threshold triggers:
  - ContractStatus → DEFAULTED
  - All open orders for that contract → CANCELLED
  - DEFAULT ReputationEvent created for the issuer
"""
from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import settings
from app.models.contract import Contract, ContractStatus
from app.models.order import Order, OrderStatus
from app.models.settlement import IncomeReport, IncomeReportStatus
from app.models.user import ReputationEvent, ReputationEventType, User


# ── shared helpers ────────────────────────────────────────────────────────────

def apply_penalty(
    user_id: uuid.UUID,
    event_type: ReputationEventType,
    penalty_points: float,
    description: str,
    db: Session,
    contract_id: Optional[uuid.UUID] = None,
) -> None:
    """Deduct penalty_points from reputation_score (floor 0) and persist an event."""
    user = db.query(User).filter(User.id == user_id).first()
    if user:
        user.reputation_score = max(0.0, user.reputation_score - penalty_points)
    db.add(ReputationEvent(
        user_id=user_id,
        contract_id=contract_id,
        event_type=event_type,
        penalty_points=penalty_points,
        description=description,
    ))


def apply_on_time_bonus(user_id: uuid.UUID, db: Session) -> None:
    """Silently increase score for an on-time report (capped at 100)."""
    user = db.query(User).filter(User.id == user_id).first()
    if user:
        user.reputation_score = min(100.0, user.reputation_score + settings.on_time_report_bonus)


# ── default detection (Celery-facing) ────────────────────────────────────────

def detect_and_apply_defaults(db: Session) -> int:
    """
    Inspect every ACTIVE contract for a consecutive OVERDUE streak.
    When the streak reaches default_consecutive_threshold:
      - Contract → DEFAULTED
      - All open orders cancelled (Postgres + Redis best-effort)
      - DEFAULT reputation event recorded for the issuer

    Returns the number of contracts newly defaulted.
    """
    contracts = (
        db.query(Contract)
        .filter(Contract.status == ContractStatus.ACTIVE)
        .all()
    )

    count = 0
    for contract in contracts:
        # Most-recent reports first so we can count the leading OVERDUE streak
        reports = (
            db.query(IncomeReport)
            .filter(IncomeReport.contract_id == contract.id)
            .order_by(IncomeReport.period_start.desc())
            .all()
        )

        consecutive = 0
        for report in reports:
            if report.status == IncomeReportStatus.OVERDUE:
                consecutive += 1
            else:
                break   # streak broken by a DISTRIBUTED or PENDING report

        if consecutive < settings.default_consecutive_threshold:
            continue

        # ── DEFAULT ──────────────────────────────────────────────────────────
        contract.status = ContractStatus.DEFAULTED

        open_orders = (
            db.query(Order)
            .filter(
                Order.contract_id == contract.id,
                Order.status.in_([OrderStatus.OPEN, OrderStatus.PARTIAL]),
            )
            .all()
        )
        for order in open_orders:
            order.status = OrderStatus.CANCELLED
            try:
                from app.services.order_book import remove_from_book
                remove_from_book(str(order.id), str(order.contract_id), order.side.value)
            except Exception:
                pass  # Redis failure is non-fatal

        apply_penalty(
            user_id=contract.issuer_id,
            event_type=ReputationEventType.DEFAULT,
            penalty_points=settings.default_reputation_penalty,
            description=(
                f"Contract '{contract.title}' defaulted after "
                f"{consecutive} consecutive missed reporting periods"
            ),
            db=db,
            contract_id=contract.id,
        )
        count += 1

    if count:
        db.commit()
    return count


# ── query helper (REST-facing) ────────────────────────────────────────────────

def get_reputation_summary(
    user_id: uuid.UUID, db: Session, limit: int = 20
) -> Optional[dict]:
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return None

    total = db.query(func.count(ReputationEvent.id)).filter(
        ReputationEvent.user_id == user_id
    ).scalar()

    events = (
        db.query(ReputationEvent)
        .filter(ReputationEvent.user_id == user_id)
        .order_by(ReputationEvent.created_at.desc())
        .limit(limit)
        .all()
    )

    return dict(
        user_id=user.id,
        full_name=user.full_name,
        reputation_score=user.reputation_score,
        total_events=total,
        events=events,
    )
