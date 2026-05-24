from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, field_validator

from app.models.contract import ContractStatus


class ContractCreate(BaseModel):
    title: str
    description: Optional[str] = None
    income_pct: float
    term_years: int
    ipo_price_per_share: Decimal

    @field_validator("income_pct")
    @classmethod
    def pct_range(cls, v: float) -> float:
        if not (0 < v <= 49):
            raise ValueError("income_pct must be between 0 (exclusive) and 49 (inclusive)")
        return round(v, 4)

    @field_validator("term_years")
    @classmethod
    def term_range(cls, v: int) -> int:
        if not (1 <= v <= 30):
            raise ValueError("term_years must be between 1 and 30")
        return v

    @field_validator("ipo_price_per_share")
    @classmethod
    def price_positive(cls, v: Decimal) -> Decimal:
        if v <= 0:
            raise ValueError("IPO price per share must be positive")
        return v


class ContractUpdate(BaseModel):
    """Only allowed while status == DRAFT."""
    title: Optional[str] = None
    description: Optional[str] = None
    income_pct: Optional[float] = None
    term_years: Optional[int] = None
    ipo_price_per_share: Optional[Decimal] = None

    @field_validator("income_pct")
    @classmethod
    def pct_range(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and not (0 < v <= 49):
            raise ValueError("income_pct must be between 0 (exclusive) and 49 (inclusive)")
        return v

    @field_validator("term_years")
    @classmethod
    def term_range(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and not (1 <= v <= 30):
            raise ValueError("term_years must be between 1 and 30")
        return v


class ContractOut(BaseModel):
    id: UUID
    issuer_id: UUID
    title: str
    description: Optional[str]
    income_pct: float
    term_years: int
    total_shares: int
    ipo_price_per_share: Decimal
    status: ContractStatus
    start_date: Optional[date]
    end_date: Optional[date]
    last_price: Optional[Decimal]
    last_traded_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class IssuerSummaryOut(BaseModel):
    """Lightweight issuer card shown alongside every contract listing."""
    id: UUID
    full_name: str
    reputation_score: float
    profile_completeness: float
    headline: Optional[str]


class ContractDetailOut(ContractOut):
    """Full contract view including issuer prospectus summary."""
    issuer: IssuerSummaryOut
    shares_held_by_issuer: int   # shares not yet sold into the market
    shares_in_circulation: int   # shares held by third-party investors


class IssuanceCapacityOut(BaseModel):
    total_pct_issued: float
    remaining_pct: float
    max_pct: float = 49.0


class BuybackRequest(BaseModel):
    """Issuer bids to repurchase shares currently held by third-party investors."""
    price_per_share: Decimal
    quantity: int

    @field_validator("quantity")
    @classmethod
    def qty_positive(cls, v: int) -> int:
        if v < 1:
            raise ValueError("Quantity must be at least 1")
        return v

    @field_validator("price_per_share")
    @classmethod
    def price_positive(cls, v: Decimal) -> Decimal:
        if v <= 0:
            raise ValueError("Price must be positive")
        return v
