"""
Shared order lifecycle logic — used by both the orders router (regular
limit orders) and the contracts router (issuer buyback bids).

Does NOT run the matching engine; that is Phase 5's job.
Every function writes to Postgres first, then syncs Redis best-effort.
"""
from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.contract import Contract, ContractStatus
from app.models.order import Order, OrderSide, OrderStatus
from app.models.position import Position


def get_available_to_sell(user_id: uuid.UUID, contract_id: uuid.UUID, db: Session) -> int:
    """
    Shares a user can still commit to open ask orders:
      position.shares_held  −  sum of their existing open ask quantities
    """
    position = (
        db.query(Position)
        .filter(Position.holder_id == user_id, Position.contract_id == contract_id)
        .first()
    )
    held = position.shares_held if position else 0

    committed = db.query(
        func.coalesce(func.sum(Order.quantity_remaining), 0)
    ).filter(
        Order.user_id == user_id,
        Order.contract_id == contract_id,
        Order.side == OrderSide.ASK,
        Order.status.in_([OrderStatus.OPEN, OrderStatus.PARTIAL]),
    ).scalar()

    return held - int(committed)


def place_order(
    user_id: uuid.UUID,
    contract_id: uuid.UUID,
    side: OrderSide,
    price_per_share: Decimal,
    quantity: int,
    db: Session,
    is_buyback: bool = False,
) -> tuple:
    """
    Validate → write Postgres → run matching engine → commit → return (Order, list[Trade]).
    All writes share a single transaction: db.flush() per step, db.commit() once at the end.
    """
    contract = (
        db.query(Contract)
        .filter(Contract.id == contract_id, Contract.status == ContractStatus.ACTIVE)
        .first()
    )
    if not contract:
        raise ValueError("Contract not found or not active")

    if side == OrderSide.ASK:
        available = get_available_to_sell(user_id, contract_id, db)
        if quantity > available:
            raise ValueError(
                f"Insufficient shares: {available} available to sell "
                f"(held minus existing open asks)"
            )

    order = Order(
        contract_id=contract_id,
        user_id=user_id,
        side=side,
        price_per_share=price_per_share,
        quantity=quantity,
        quantity_filled=0,
        quantity_remaining=quantity,
        is_buyback=is_buyback,
    )
    db.add(order)
    db.flush()  # populate order.id inside the transaction

    try:
        from app.services.order_book import add_to_book
        add_to_book(order)
    except Exception:
        pass  # Redis unavailable — Postgres remains the source of truth

    from app.services.matching_engine import run_matching
    trades = run_matching(order, db)

    db.commit()
    db.refresh(order)
    return order, trades


def cancel_order(order_id: uuid.UUID, user_id: uuid.UUID, db: Session) -> Order:
    """Cancel an open or partially filled order and remove it from the Redis book."""
    order = (
        db.query(Order)
        .filter(
            Order.id == order_id,
            Order.user_id == user_id,
            Order.status.in_([OrderStatus.OPEN, OrderStatus.PARTIAL]),
        )
        .first()
    )
    if not order:
        raise ValueError("Order not found or already filled / cancelled")

    order.status = OrderStatus.CANCELLED
    db.commit()
    db.refresh(order)

    try:
        from app.services.order_book import remove_from_book
        remove_from_book(str(order.id), str(order.contract_id), order.side.value)
    except Exception:
        pass

    return order
