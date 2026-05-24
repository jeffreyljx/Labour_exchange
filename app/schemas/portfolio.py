from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from pydantic import BaseModel


class HoldingOut(BaseModel):
    contract_id: UUID
    contract_title: str
    issuer_id: UUID
    issuer_name: str
    income_pct: float
    term_years: int
    contract_status: str

    shares_held: int
    total_shares: int
    ownership_pct: float  # shares_held / total_shares * 100

    # P&L
    average_cost_basis: Optional[Decimal]  # weighted avg price paid per share
    last_price: Optional[Decimal]          # contract.last_price (most recent trade)
    cost_basis_total: Optional[Decimal]    # average_cost_basis * shares_held
    current_value: Optional[Decimal]       # last_price * shares_held
    unrealized_pnl: Optional[Decimal]      # current_value - cost_basis_total
    unrealized_pnl_pct: Optional[float]    # unrealized_pnl / cost_basis_total * 100

    total_distributions_received: Decimal  # lifetime income payouts for this position


class PortfolioSummaryOut(BaseModel):
    total_positions: int
    total_current_value: Decimal
    total_cost_basis: Decimal
    total_unrealized_pnl: Decimal
    total_distributions_received: Decimal
    total_return: Decimal  # unrealized_pnl + distributions


class DistributionOut(BaseModel):
    id: UUID
    contract_id: UUID
    contract_title: str
    income_report_id: UUID
    period_start: date
    period_end: date
    shares_held_at_snapshot: int
    amount_per_share: Decimal
    total_amount: Decimal
    paid_at: datetime
