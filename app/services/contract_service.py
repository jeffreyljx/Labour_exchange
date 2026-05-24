from __future__ import annotations

import uuid
from datetime import date
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import settings
from app.models.contract import Contract, ContractStatus
from app.models.position import Position


def get_total_issued_pct(
    user_id: uuid.UUID,
    db: Session,
    exclude_id: Optional[uuid.UUID] = None,
) -> float:
    """Sum income_pct across all DRAFT + ACTIVE contracts for this issuer."""
    q = db.query(func.coalesce(func.sum(Contract.income_pct), 0.0)).filter(
        Contract.issuer_id == user_id,
        Contract.status.in_([ContractStatus.DRAFT, ContractStatus.ACTIVE]),
    )
    if exclude_id:
        q = q.filter(Contract.id != exclude_id)
    return float(q.scalar())


def check_issuance_capacity(
    user_id: uuid.UUID,
    new_pct: float,
    db: Session,
    exclude_id: Optional[uuid.UUID] = None,
) -> bool:
    """Return True if adding new_pct would not breach the 49 % cap."""
    existing = get_total_issued_pct(user_id, db, exclude_id=exclude_id)
    return (existing + new_pct) <= settings.max_income_pct_per_issuer


def activate_contract(contract: Contract, db: Session) -> None:
    """
    Transition a DRAFT contract to ACTIVE:
      - Re-validates the 49 % cap (race-condition guard)
      - Sets start / end dates
      - Mints all shares to the issuer's Position
    """
    if contract.status != ContractStatus.DRAFT:
        raise ValueError("Only DRAFT contracts can be activated")

    if not check_issuance_capacity(
        contract.issuer_id, contract.income_pct, db, exclude_id=contract.id
    ):
        raise ValueError(
            f"Activating this contract would exceed the "
            f"{settings.max_income_pct_per_issuer}% issuance cap"
        )

    today = date.today()
    end_year = today.year + contract.term_years
    try:
        end_date = today.replace(year=end_year)
    except ValueError:
        # Edge case: Feb 29 in a non-leap year
        end_date = today.replace(year=end_year, day=28)

    contract.status = ContractStatus.ACTIVE
    contract.start_date = today
    contract.end_date = end_date

    # Mint all shares to the issuer — they sell through the order book
    existing_position = db.query(Position).filter(
        Position.contract_id == contract.id,
        Position.holder_id == contract.issuer_id,
    ).first()

    if existing_position:
        existing_position.shares_held = contract.total_shares
    else:
        db.add(Position(
            contract_id=contract.id,
            holder_id=contract.issuer_id,
            shares_held=contract.total_shares,
        ))

    db.commit()
    db.refresh(contract)


def expire_overdue(db: Session) -> int:
    """Mark all ACTIVE contracts whose end_date has passed as EXPIRED.

    Called lazily on reads and by the quarterly settlement task.
    Returns the count of newly expired contracts.
    """
    today = date.today()
    result = (
        db.query(Contract)
        .filter(Contract.status == ContractStatus.ACTIVE, Contract.end_date < today)
        .all()
    )
    for c in result:
        c.status = ContractStatus.EXPIRED
    if result:
        db.commit()
    return len(result)
