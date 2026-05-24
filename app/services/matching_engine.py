"""
Price-time priority matching engine.

Triggered synchronously inside place_order after the incoming order is
flushed to Postgres.  All mutations — trades, order fills, position moves,
contract price stamp — are flushed per iteration but committed *once* by
the caller, giving a single atomic transaction for placement + matching.

Algorithm
---------
1. Find the best resting order on the opposing side (Postgres, price-time priority).
2. If no match or price doesn't cross → stop; incoming order rests in book.
3. If same user on both sides       → stop (self-trade prevention).
4. fill_qty  = min(incoming.remaining, opposing.remaining)
   fill_price = opposing.price_per_share  (maker sets the price)
5. Create Trade, apply fills, move positions, stamp contract, sync Redis.
6. Repeat until incoming is fully filled or no more matches exist.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy.orm import Session

from app.models.contract import Contract
from app.models.order import Order, OrderSide, OrderStatus
from app.models.position import Position
from app.models.trade import Trade


def run_matching(incoming: Order, db: Session) -> list[Trade]:
    """
    Match `incoming` against the resting book.
    Returns every Trade created (empty list if the order simply rests).
    """
    trades: list[Trade] = []

    while incoming.quantity_remaining > 0:
        opposing = _best_opposing(incoming, db)

        if opposing is None:
            break  # book is empty on the opposing side

        # Price-crossing check
        if incoming.side == OrderSide.BID:
            if incoming.price_per_share < opposing.price_per_share:
                break  # bid is too low
        else:
            if incoming.price_per_share > opposing.price_per_share:
                break  # ask is too high

        # Self-trade prevention — incoming order rests
        if opposing.user_id == incoming.user_id:
            break

        fill_qty: int = min(incoming.quantity_remaining, opposing.quantity_remaining)
        fill_price: Decimal = opposing.price_per_share  # maker's price

        if incoming.side == OrderSide.BID:
            buyer_order, seller_order = incoming, opposing
        else:
            buyer_order, seller_order = opposing, incoming

        trade = Trade(
            contract_id=incoming.contract_id,
            buy_order_id=buyer_order.id,
            sell_order_id=seller_order.id,
            buyer_id=buyer_order.user_id,
            seller_id=seller_order.user_id,
            price_per_share=fill_price,
            quantity=fill_qty,
            total_value=fill_price * fill_qty,
        )
        db.add(trade)

        _apply_fill(incoming, fill_qty)
        _apply_fill(opposing, fill_qty)
        _move_shares(buyer_order.user_id, seller_order.user_id,
                     incoming.contract_id, fill_qty, db)
        _stamp_contract(incoming.contract_id, fill_price, db)
        _sync_redis(incoming, opposing, trade)

        db.flush()  # make fills visible within this session before next iteration
        trades.append(trade)

    return trades


# ── private helpers ───────────────────────────────────────────────────────────

def _best_opposing(order: Order, db: Session) -> Optional[Order]:
    """
    Fetch the single best resting counter-order using Postgres.
    Price-time priority: best price first, then earliest creation time.
    Excludes the incoming order itself (safety guard).
    """
    q = (
        db.query(Order)
        .filter(
            Order.contract_id == order.contract_id,
            Order.id != order.id,
            Order.status.in_([OrderStatus.OPEN, OrderStatus.PARTIAL]),
        )
    )
    if order.side == OrderSide.BID:
        q = q.filter(Order.side == OrderSide.ASK).order_by(
            Order.price_per_share.asc(),
            Order.created_at.asc(),
        )
    else:
        q = q.filter(Order.side == OrderSide.BID).order_by(
            Order.price_per_share.desc(),
            Order.created_at.asc(),
        )
    return q.first()


def _apply_fill(order: Order, fill_qty: int) -> None:
    order.quantity_filled += fill_qty
    order.quantity_remaining -= fill_qty
    order.status = (
        OrderStatus.FILLED if order.quantity_remaining == 0 else OrderStatus.PARTIAL
    )


def _move_shares(
    buyer_id: uuid.UUID,
    seller_id: uuid.UUID,
    contract_id: uuid.UUID,
    qty: int,
    db: Session,
) -> None:
    """Transfer `qty` shares from seller to buyer, upserting Position records."""
    seller_pos = (
        db.query(Position)
        .filter(Position.holder_id == seller_id, Position.contract_id == contract_id)
        .first()
    )
    if seller_pos:
        seller_pos.shares_held -= qty

    buyer_pos = (
        db.query(Position)
        .filter(Position.holder_id == buyer_id, Position.contract_id == contract_id)
        .first()
    )
    if buyer_pos:
        buyer_pos.shares_held += qty
    else:
        db.add(Position(contract_id=contract_id, holder_id=buyer_id, shares_held=qty))


def _stamp_contract(
    contract_id: uuid.UUID, fill_price: Decimal, db: Session
) -> None:
    """Update the denormalized last_price / last_traded_at on the contract."""
    contract = db.query(Contract).filter(Contract.id == contract_id).first()
    if contract:
        contract.last_price = fill_price
        contract.last_traded_at = datetime.now(timezone.utc)


def _sync_redis(incoming: Order, opposing: Order, trade: Trade) -> None:
    """Best-effort Redis sync after a fill — never blocks on failure."""
    try:
        import json
        from app.services.order_book import remove_from_book, update_quantity
        from app.redis_client import get_redis_client as get_redis

        for o in (incoming, opposing):
            if o.quantity_remaining == 0:
                remove_from_book(str(o.id), str(o.contract_id), o.side.value)
            else:
                update_quantity(str(o.id), o.quantity_remaining)

        # Publish fill event so WebSocket subscribers receive live updates.
        event = json.dumps({
            "type": "trade",
            "contract_id": str(trade.contract_id),
            "price": str(trade.price_per_share),
            "quantity": trade.quantity,
            "total_value": str(trade.total_value),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        get_redis().publish(f"ob:events:{trade.contract_id}", event)
    except Exception:
        pass
