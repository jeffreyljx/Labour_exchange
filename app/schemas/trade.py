from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import List
from uuid import UUID

from pydantic import BaseModel

from app.schemas.order import OrderOut


class TradeOut(BaseModel):
    id: UUID
    contract_id: UUID
    buy_order_id: UUID
    sell_order_id: UUID
    buyer_id: UUID
    seller_id: UUID
    price_per_share: Decimal
    quantity: int
    total_value: Decimal
    executed_at: datetime

    model_config = {"from_attributes": True}


class OrderPlacementResult(BaseModel):
    """
    Returned by POST /orders/ and POST /contracts/{id}/buyback.

    `fills` contains every trade executed immediately against the resting book.
    An empty list means the order is resting (no counterpart met the price).
    """
    order: OrderOut
    fills: List[TradeOut]
    filled_quantity: int
    remaining_quantity: int
    message: str
