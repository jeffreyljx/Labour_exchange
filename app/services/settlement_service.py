"""
Settlement engine — income reporting and quarterly distribution processing.

Flow
----
1. Daily Celery task calls generate_expected_reports():
   Creates a PENDING placeholder IncomeReport for each completed 91-day
   quarter of every active contract that doesn't already have one.

2. Daily Celery task calls mark_overdue_reports():
   Any PENDING placeholder (gross_income IS NULL) whose due_date has
   passed is transitioned to OVERDUE and a reputation penalty applied.

3. Issuer calls submit_income_report() via REST:
   Fills in gross_income on an existing PENDING/OVERDUE placeholder, or
   creates a new record for periods the scan hasn't reached yet.
   Auto-verifies and immediately runs process_distributions().

4. process_distributions() snapshots all non-issuer positions and mints
   one Distribution record per external holder.  The per-share rate is
   fixed: total_distribution / contract.total_shares, so each share
   always carries the same economic weight regardless of how many shares
   remain with the issuer.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy.orm import Session

from app.config import settings
from app.models.contract import Contract, ContractStatus
from app.models.position import Position
from app.models.settlement import Distribution, IncomeReport, IncomeReportStatus
from app.models.user import ReputationEvent, ReputationEventType, User


_ZERO = Decimal("0")


# ── period helpers ────────────────────────────────────────────────────────────

def _expected_periods(
    contract: Contract, today: date
) -> list[tuple[date, date, date]]:
    """
    Returns (period_start, period_end, due_date) for every completed
    91-day reporting window since the contract's start_date.
    Periods whose period_end >= today are excluded (not yet finished).
    """
    if not contract.start_date or not contract.end_date:
        return []

    period_days = settings.report_period_days
    grace_days = settings.report_due_grace_days
    periods: list[tuple[date, date, date]] = []
    period_start = contract.start_date

    while period_start < contract.end_date:
        period_end = min(
            period_start + timedelta(days=period_days - 1),
            contract.end_date - timedelta(days=1),
        )
        if period_end >= today:
            break  # period hasn't finished yet
        due_date = period_end + timedelta(days=grace_days)
        periods.append((period_start, period_end, due_date))
        period_start = period_end + timedelta(days=1)

    return periods


# ── Celery-facing functions (called from app.tasks.settlement) ────────────────

def generate_expected_reports(db: Session) -> int:
    """
    Create PENDING placeholder IncomeReport records for every completed
    quarter of every ACTIVE contract that has no report yet.
    Returns the number of new records created.
    """
    today = date.today()
    contracts = (
        db.query(Contract)
        .filter(Contract.status == ContractStatus.ACTIVE)
        .all()
    )
    count = 0
    for contract in contracts:
        for period_start, period_end, due_date in _expected_periods(contract, today):
            exists = (
                db.query(IncomeReport.id)
                .filter(
                    IncomeReport.contract_id == contract.id,
                    IncomeReport.period_start == period_start,
                )
                .first()
            )
            if exists:
                continue
            db.add(IncomeReport(
                contract_id=contract.id,
                issuer_id=contract.issuer_id,
                period_start=period_start,
                period_end=period_end,
                due_date=due_date,
                gross_income=None,
                contract_pct_snapshot=contract.income_pct,
                status=IncomeReportStatus.PENDING,
            ))
            count += 1

    if count:
        db.commit()
    return count


def mark_overdue_reports(db: Session) -> int:
    """
    Transition PENDING placeholder reports (not yet submitted) whose
    due_date has passed to OVERDUE, and deduct reputation points from
    the issuer.  Returns count of reports transitioned.
    """
    today = date.today()
    overdue_reports = (
        db.query(IncomeReport)
        .filter(
            IncomeReport.status == IncomeReportStatus.PENDING,
            IncomeReport.gross_income.is_(None),
            IncomeReport.due_date < today,
        )
        .all()
    )

    count = 0
    for report in overdue_reports:
        report.status = IncomeReportStatus.OVERDUE

        issuer = db.query(User).filter(User.id == report.issuer_id).first()
        if issuer:
            penalty = settings.overdue_reputation_penalty
            issuer.reputation_score = max(0.0, issuer.reputation_score - penalty)
            db.add(ReputationEvent(
                user_id=report.issuer_id,
                contract_id=report.contract_id,
                event_type=ReputationEventType.MISSED_REPORT,
                penalty_points=penalty,
                description=(
                    f"Missed quarterly income report for period "
                    f"{report.period_start} – {report.period_end}"
                ),
            ))
        count += 1

    if count:
        db.commit()
    return count


# ── distribution processing ───────────────────────────────────────────────────

def process_distributions(report: IncomeReport, db: Session) -> list[Distribution]:
    """
    Snapshot all external shareholder positions and mint Distribution records.

    amount_per_share = (gross_income * income_pct%) / total_shares (1000)
    Only non-issuer holders receive distributions — the issuer keeps the
    proportional amount for shares they still hold (net payout is correct).
    """
    contract = report.contract
    gross = report.gross_income  # guaranteed non-None when called from submit
    total_distribution = gross * Decimal(str(contract.income_pct)) / Decimal("100")
    amount_per_share = total_distribution / contract.total_shares

    positions = (
        db.query(Position)
        .filter(
            Position.contract_id == contract.id,
            Position.holder_id != contract.issuer_id,
            Position.shares_held > 0,
        )
        .all()
    )

    created: list[Distribution] = []
    for pos in positions:
        dist = Distribution(
            income_report_id=report.id,
            contract_id=contract.id,
            holder_id=pos.holder_id,
            shares_held_at_snapshot=pos.shares_held,
            amount_per_share=amount_per_share,
            total_amount=amount_per_share * pos.shares_held,
        )
        db.add(dist)
        created.append(dist)

    now = datetime.now(timezone.utc)
    report.total_distribution = total_distribution
    report.distribution_per_share = amount_per_share
    report.status = IncomeReportStatus.DISTRIBUTED
    report.verified_at = now
    report.distributed_at = now
    return created


# ── REST-facing function ──────────────────────────────────────────────────────

def submit_income_report(
    issuer_id: uuid.UUID,
    contract_id: uuid.UUID,
    period_start: date,
    period_end: date,
    gross_income: Decimal,
    db: Session,
) -> IncomeReport:
    """
    Issuer submits gross_income for a completed reporting period.

    Looks for an existing PENDING / OVERDUE placeholder first (created by
    the Celery scan).  If none exists, creates a new record — this handles
    both on-time and late submissions for periods the scan hasn't processed.
    Auto-verifies and immediately calls process_distributions().
    """
    contract = (
        db.query(Contract)
        .filter(
            Contract.id == contract_id,
            Contract.issuer_id == issuer_id,
            Contract.status == ContractStatus.ACTIVE,
        )
        .first()
    )
    if not contract:
        raise ValueError("Active contract not found or you are not the issuer")
    if period_start < contract.start_date:
        raise ValueError("period_start is before the contract start date")
    if period_end >= date.today():
        raise ValueError("Cannot report for an unfinished period — period_end must be in the past")
    if period_end <= period_start:
        raise ValueError("period_end must be after period_start")

    existing = (
        db.query(IncomeReport)
        .filter(
            IncomeReport.contract_id == contract_id,
            IncomeReport.period_start == period_start,
        )
        .first()
    )

    if existing:
        if existing.status == IncomeReportStatus.DISTRIBUTED:
            raise ValueError("A report for this period has already been distributed")
        if existing.gross_income is not None:
            raise ValueError("A report has already been submitted for this period")
        # Fill in the placeholder created by the Celery scan
        existing.gross_income = gross_income
        existing.submitted_at = datetime.now(timezone.utc)
        existing.contract_pct_snapshot = contract.income_pct
        report = existing
    else:
        due_date = period_end + timedelta(days=settings.report_due_grace_days)
        report = IncomeReport(
            contract_id=contract_id,
            issuer_id=issuer_id,
            period_start=period_start,
            period_end=period_end,
            due_date=due_date,
            gross_income=gross_income,
            contract_pct_snapshot=contract.income_pct,
            status=IncomeReportStatus.PENDING,
        )
        db.add(report)

    db.flush()  # populate report.id before creating distributions
    process_distributions(report, db)

    # Reputation adjustment — late submission penalised, on-time rewarded silently
    from app.services.reputation_service import apply_on_time_bonus, apply_penalty
    from app.models.user import ReputationEventType

    if report.due_date < date.today():
        apply_penalty(
            user_id=issuer_id,
            event_type=ReputationEventType.LATE_REPORT,
            penalty_points=settings.late_report_penalty,
            description=f"Late income report submitted for period {period_start} – {period_end}",
            db=db,
            contract_id=contract_id,
        )
    else:
        apply_on_time_bonus(issuer_id, db)

    db.commit()
    db.refresh(report)
    return report
