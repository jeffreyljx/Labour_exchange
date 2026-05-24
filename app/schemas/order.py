from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, field_validator

from app.models.order import OrderSide, OrderStatus


class OrderCreate(BaseModel):
    contract_id: UUID
    side: OrderSide
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


class OrderOut(BaseModel):
    id: UUID
    contract_id: UUID
    user_id: UUID
    side: OrderSide
    price_per_share: Decimal
    quantity: int
    quantity_filled: int
    quantity_remaining: int
    status: OrderStatus
    is_buyback: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class OrderBookLevel(BaseModel):
    price: Decimal
    quantity: int
    order_count: int


class OrderBookOut(BaseModel):
    contract_id: UUID
    bids: List[OrderBookLevel]   # sorted high → low
    asks: List[OrderBookLevel]   # sorted low → high
    best_bid: Optional[Decimal]
    best_ask: Optional[Decimal]
    spread: Optional[Decimal]
    mid_price: Optional[Decimal]
