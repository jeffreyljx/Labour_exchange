from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, field_validator, model_validator

from app.models.settlement import IncomeReportStatus


class IncomeReportSubmit(BaseModel):
    contract_id: UUID
    period_start: date
    period_end: date
    gross_income: Decimal

    @field_validator("gross_income")
    @classmethod
    def income_positive(cls, v: Decimal) -> Decimal:
        if v <= 0:
            raise ValueError("gross_income must be positive")
        return v

    @model_validator(mode="after")
    def period_valid(self) -> "IncomeReportSubmit":
        if self.period_end <= self.period_start:
            raise ValueError("period_end must be after period_start")
        return self


class IncomeReportOut(BaseModel):
    id: UUID
    contract_id: UUID
    issuer_id: UUID
    period_start: date
    period_end: date
    due_date: date
    gross_income: Optional[Decimal]       # None for unsubmitted placeholders
    contract_pct_snapshot: float
    total_distribution: Optional[Decimal]
    distribution_per_share: Optional[Decimal]
    status: IncomeReportStatus
    submitted_at: datetime
    verified_at: Optional[datetime]
    distributed_at: Optional[datetime]

    model_config = {"from_attributes": True}
