from __future__ import annotations

import enum
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import Date, DateTime, Enum, Float, ForeignKey, Integer, Numeric
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.models.base import Base


class IncomeReportStatus(str, enum.Enum):
    PENDING = "pending"
    VERIFIED = "verified"
    DISTRIBUTED = "distributed"
    OVERDUE = "overdue"


class IncomeReport(Base):
    __tablename__ = "income_reports"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    contract_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("contracts.id"), nullable=False, index=True)
    issuer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)

    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=False)

    # None until the issuer submits; auto-generated placeholders start as NULL
    gross_income: Mapped[Optional[Decimal]] = mapped_column(Numeric(16, 2), nullable=True)
    contract_pct_snapshot: Mapped[float] = mapped_column(Float, nullable=False)  # snapshot of % at report time
    total_distribution: Mapped[Optional[Decimal]] = mapped_column(Numeric(16, 4), nullable=True)
    distribution_per_share: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 6), nullable=True)

    status: Mapped[IncomeReportStatus] = mapped_column(Enum(IncomeReportStatus), default=IncomeReportStatus.PENDING)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    distributed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    contract: Mapped["Contract"] = relationship(back_populates="income_reports")
    distributions: Mapped[list["Distribution"]] = relationship(back_populates="income_report")


class Distribution(Base):
    __tablename__ = "distributions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    income_report_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("income_reports.id"), nullable=False)
    contract_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("contracts.id"), nullable=False)
    holder_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)

    shares_held_at_snapshot: Mapped[int] = mapped_column(Integer, nullable=False)
    amount_per_share: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(16, 4), nullable=False)
    paid_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    income_report: Mapped["IncomeReport"] = relationship(back_populates="distributions")
    contract: Mapped["Contract"] = relationship(back_populates="distributions")
    holder: Mapped["User"] = relationship(back_populates="distributions_received")
