from __future__ import annotations

import enum
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import Date, DateTime, Enum, Float, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.models.base import Base


class ContractStatus(str, enum.Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    EXPIRED = "expired"
    DEFAULTED = "defaulted"


class Contract(Base):
    __tablename__ = "contracts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    issuer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    income_pct: Mapped[float] = mapped_column(Float, nullable=False)       # e.g. 20.0 = 20%
    term_years: Mapped[int] = mapped_column(Integer, nullable=False)
    total_shares: Mapped[int] = mapped_column(Integer, default=1000)
    ipo_price_per_share: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)

    status: Mapped[ContractStatus] = mapped_column(Enum(ContractStatus), default=ContractStatus.DRAFT, index=True)
    start_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    end_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)

    # Denormalized by the matching engine on every fill — lets UIs render live tickers
    # without subquerying trades on every contract list request
    last_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 4), nullable=True)
    last_traded_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    issuer: Mapped["User"] = relationship(back_populates="contracts_issued", foreign_keys=[issuer_id])
    positions: Mapped[list["Position"]] = relationship(back_populates="contract")
    orders: Mapped[list["Order"]] = relationship(back_populates="contract")
    trades: Mapped[list["Trade"]] = relationship(back_populates="contract")
    income_reports: Mapped[list["IncomeReport"]] = relationship(back_populates="contract")
    distributions: Mapped[list["Distribution"]] = relationship(back_populates="contract")
    reputation_events: Mapped[list["ReputationEvent"]] = relationship(foreign_keys="ReputationEvent.contract_id")
