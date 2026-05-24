from __future__ import annotations

import enum
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, Numeric
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.models.base import Base


class OrderSide(str, enum.Enum):
    BID = "bid"
    ASK = "ask"


class OrderStatus(str, enum.Enum):
    OPEN = "open"
    PARTIAL = "partial"
    FILLED = "filled"
    CANCELLED = "cancelled"


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    contract_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("contracts.id"), nullable=False, index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)

    side: Mapped[OrderSide] = mapped_column(Enum(OrderSide), nullable=False)
    price_per_share: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    quantity_filled: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    quantity_remaining: Mapped[int] = mapped_column(Integer, nullable=False)

    status: Mapped[OrderStatus] = mapped_column(Enum(OrderStatus), default=OrderStatus.OPEN, index=True)
    is_buyback: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    contract: Mapped["Contract"] = relationship(back_populates="orders")
    user: Mapped["User"] = relationship(back_populates="orders")
    buy_trades: Mapped[list["Trade"]] = relationship(foreign_keys="Trade.buy_order_id", back_populates="buy_order")
    sell_trades: Mapped[list["Trade"]] = relationship(foreign_keys="Trade.sell_order_id", back_populates="sell_order")
