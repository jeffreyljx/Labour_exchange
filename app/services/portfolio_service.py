"""
Portfolio computation layer.

All P&L figures use the average-cost method:
  - Non-issuers: weighted average of all buy-side trades for this contract.
  - Issuers:     blended — original issuance shares at ipo_price_per_share,
                 buyback shares at their weighted average trade price.

Because this is an exchange prototype we do not adjust cost basis on partial
sells (FIFO / specific-lot accounting).  Unrealized P&L is therefore an
approximation when the holder has sold-and-reacquired shares.
"""
from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.contract import Contract
from app.models.position import Position
from app.models.settlement import Distribution, IncomeReport
from app.models.trade import Trade


_ZERO = Decimal("0")


# ── private helpers ───────────────────────────────────────────────────────────

def _distribution_total(user_id: uuid.UUID, contract_id: uuid.UUID, db: Session) -> Decimal:
    return db.query(
        func.coalesce(func.sum(Distribution.total_amount), _ZERO)
    ).filter(
        Distribution.holder_id == user_id,
        Distribution.contract_id == contract_id,
    ).scalar()


def _build_holding(position: Position, user_id: uuid.UUID, db: Session) -> dict:
    contract: Contract = position.contract
    shares = position.shares_held

    # All buy trades for this user + contract
    buy_rows = (
        db.query(Trade.price_per_share, Trade.quantity)
        .filter(Trade.buyer_id == user_id, Trade.contract_id == contract.id)
        .all()
    )
    total_shares_bought = sum(r.quantity for r in buy_rows)
    total_buy_value: Decimal = sum((r.price_per_share * r.quantity for r in buy_rows), _ZERO)

    if position.holder_id == contract.issuer_id:
        # Shares the issuer holds that came from original issuance (not buybacks)
        original_shares_held = max(0, shares - total_shares_bought)
        buyback_shares_held = shares - original_shares_held
        ipo_cost = contract.ipo_price_per_share * original_shares_held
        # Prorated buyback cost for only the shares still held
        if total_shares_bought > 0:
            avg_buyback_price = total_buy_value / total_shares_bought
            buyback_cost = avg_buyback_price * buyback_shares_held
        else:
            buyback_cost = _ZERO
        total_cost = ipo_cost + buyback_cost
        avg_cost: Optional[Decimal] = total_cost / shares if shares > 0 else contract.ipo_price_per_share
    elif total_shares_bought > 0:
        avg_cost = total_buy_value / total_shares_bought
    else:
        avg_cost = None  # should not occur for a non-issuer position

    last_price = contract.last_price
    cost_basis_total = avg_cost * shares if avg_cost is not None else None
    current_value = last_price * shares if last_price is not None else None

    if cost_basis_total is not None and current_value is not None:
        unrealized_pnl: Optional[Decimal] = current_value - cost_basis_total
        unrealized_pnl_pct: Optional[float] = (
            float(unrealized_pnl / cost_basis_total * 100)
            if cost_basis_total != _ZERO else 0.0
        )
    else:
        unrealized_pnl = None
        unrealized_pnl_pct = None

    return dict(
        contract_id=contract.id,
        contract_title=contract.title,
        issuer_id=contract.issuer_id,
        issuer_name=contract.issuer.full_name,
        income_pct=contract.income_pct,
        term_years=contract.term_years,
        contract_status=contract.status.value,
        shares_held=shares,
        total_shares=contract.total_shares,
        ownership_pct=round(shares / contract.total_shares * 100, 4),
        average_cost_basis=avg_cost,
        last_price=last_price,
        cost_basis_total=cost_basis_total,
        current_value=current_value,
        unrealized_pnl=unrealized_pnl,
        unrealized_pnl_pct=unrealized_pnl_pct,
        total_distributions_received=_distribution_total(user_id, contract.id, db),
    )


# ── public API ────────────────────────────────────────────────────────────────

def get_holdings(user_id: uuid.UUID, db: Session) -> list[dict]:
    positions = (
        db.query(Position)
        .filter(Position.holder_id == user_id, Position.shares_held > 0)
        .all()
    )
    return [_build_holding(p, user_id, db) for p in positions]


def get_holding(
    user_id: uuid.UUID, contract_id: uuid.UUID, db: Session
) -> Optional[dict]:
    position = (
        db.query(Position)
        .filter(Position.holder_id == user_id, Position.contract_id == contract_id)
        .first()
    )
    if not position or position.shares_held == 0:
        return None
    return _build_holding(position, user_id, db)


def get_portfolio_summary(user_id: uuid.UUID, db: Session) -> dict:
    holdings = get_holdings(user_id, db)

    total_current_value = sum((h["current_value"] or _ZERO) for h in holdings)
    total_cost_basis = sum((h["cost_basis_total"] or _ZERO) for h in holdings)
    total_unrealized_pnl = total_current_value - total_cost_basis

    total_distributions = db.query(
        func.coalesce(func.sum(Distribution.total_amount), _ZERO)
    ).filter(Distribution.holder_id == user_id).scalar()

    return dict(
        total_positions=len(holdings),
        total_current_value=total_current_value,
        total_cost_basis=total_cost_basis,
        total_unrealized_pnl=total_unrealized_pnl,
        total_distributions_received=total_distributions,
        total_return=total_unrealized_pnl + total_distributions,
    )


def get_distributions(
    user_id: uuid.UUID,
    db: Session,
    contract_id: Optional[uuid.UUID] = None,
    skip: int = 0,
    limit: int = 50,
) -> list[dict]:
    q = (
        db.query(Distribution, IncomeReport, Contract)
        .join(IncomeReport, Distribution.income_report_id == IncomeReport.id)
        .join(Contract, Distribution.contract_id == Contract.id)
        .filter(Distribution.holder_id == user_id)
    )
    if contract_id:
        q = q.filter(Distribution.contract_id == contract_id)

    rows = q.order_by(Distribution.paid_at.desc()).offset(skip).limit(limit).all()

    return [
        dict(
            id=dist.id,
            contract_id=dist.contract_id,
            contract_title=contract.title,
            income_report_id=dist.income_report_id,
            period_start=report.period_start,
            period_end=report.period_end,
            shares_held_at_snapshot=dist.shares_held_at_snapshot,
            amount_per_share=dist.amount_per_share,
            total_amount=dist.total_amount,
            paid_at=dist.paid_at,
        )
        for dist, report, contract in rows
    ]
