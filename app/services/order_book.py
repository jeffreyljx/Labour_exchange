"""
Redis order book — maintains two sorted sets per contract:

  ob:bids:{contract_id}   scored by price (matching engine reads highest first)
  ob:asks:{contract_id}   scored by price (matching engine reads lowest first)

Each member is an order_id string.  A companion hash stores the remaining
quantity so we can aggregate levels without round-tripping to Postgres.

All public functions are best-effort: callers catch exceptions so that a
Redis outage never blocks order placement (Postgres is the source of truth).
"""
from __future__ import annotations

import logging
from decimal import Decimal
from typing import Optional

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


# ── key helpers ───────────────────────────────────────────────────────────────

def _bids_key(contract_id: str) -> str:
    return f"ob:bids:{contract_id}"

def _asks_key(contract_id: str) -> str:
    return f"ob:asks:{contract_id}"

def _hash_key(order_id: str) -> str:
    return f"ob:order:{order_id}"

def _r():
    from app.redis_client import get_redis_client
    return get_redis_client()


# ── write path ────────────────────────────────────────────────────────────────

def add_to_book(order) -> None:
    """Sync a freshly placed (or restored) order into the Redis book."""
    r = _r()
    cid = str(order.contract_id)
    oid = str(order.id)
    key = _bids_key(cid) if order.side.value == "bid" else _asks_key(cid)
    r.zadd(key, {oid: float(order.price_per_share)})
    r.hset(_hash_key(oid), mapping={
        "side": order.side.value,
        "price": str(order.price_per_share),
        "qty": str(order.quantity_remaining),
    })


def remove_from_book(order_id: str, contract_id: str, side: str) -> None:
    """Remove a cancelled or fully filled order from the Redis book."""
    r = _r()
    key = _bids_key(contract_id) if side == "bid" else _asks_key(contract_id)
    r.zrem(key, order_id)
    r.delete(_hash_key(order_id))


def update_quantity(order_id: str, quantity_remaining: int) -> None:
    """Update remaining quantity after a partial fill."""
    _r().hset(_hash_key(order_id), "qty", str(quantity_remaining))


def rebuild_book(contract_id, db: Session) -> None:
    """
    Repopulate Redis from Postgres open orders.
    Call on cold start or after suspected Redis drift.
    """
    from app.models.order import Order, OrderStatus

    cid = str(contract_id)
    r = _r()
    r.delete(_bids_key(cid), _asks_key(cid))

    orders = (
        db.query(Order)
        .filter(
            Order.contract_id == contract_id,
            Order.status.in_([OrderStatus.OPEN, OrderStatus.PARTIAL]),
        )
        .all()
    )
    for order in orders:
        add_to_book(order)


# ── read path ─────────────────────────────────────────────────────────────────

def get_best_bid(contract_id: str) -> Optional[tuple[str, float]]:
    """Return (order_id, price) for the highest resting bid, or None."""
    result = _r().zrevrange(_bids_key(contract_id), 0, 0, withscores=True)
    return result[0] if result else None


def get_best_ask(contract_id: str) -> Optional[tuple[str, float]]:
    """Return (order_id, price) for the lowest resting ask, or None."""
    result = _r().zrange(_asks_key(contract_id), 0, 0, withscores=True)
    return result[0] if result else None


def get_book_from_redis(contract_id: str, depth: int = 10) -> Optional[dict]:
    """
    Build aggregated price-level view from Redis.
    Returns None when Redis is empty or unreachable (caller falls back to DB).
    """
    try:
        r = _r()
        cid = str(contract_id)

        bid_raw = r.zrevrange(_bids_key(cid), 0, -1, withscores=True)
        ask_raw = r.zrange(_asks_key(cid), 0, -1, withscores=True)

        if not bid_raw and not ask_raw:
            return None

        def aggregate(entries: list, descending: bool) -> list:
            levels: dict = {}
            for oid, score in entries:
                h = r.hgetall(_hash_key(oid))
                qty = int(h.get("qty", 0))
                if qty <= 0:
                    continue
                p = round(float(score), 4)
                if p not in levels:
                    levels[p] = {"price": Decimal(str(p)), "quantity": 0, "order_count": 0}
                levels[p]["quantity"] += qty
                levels[p]["order_count"] += 1
            return sorted(levels.values(), key=lambda x: x["price"], reverse=descending)[:depth]

        bids = aggregate(bid_raw, descending=True)
        asks = aggregate(ask_raw, descending=False)
        return _summarise(bids, asks, contract_id)

    except Exception as exc:
        logger.warning("Redis order book read failed (%s); will fall back to DB", exc)
        return None


def get_book_from_db(contract_id, depth: int, db: Session) -> dict:
    """Postgres fallback: aggregate OPEN/PARTIAL orders by price level."""
    from sqlalchemy import func
    from app.models.order import Order, OrderSide, OrderStatus

    def levels(side: OrderSide, asc: bool) -> list:
        rows = (
            db.query(
                Order.price_per_share,
                func.sum(Order.quantity_remaining).label("qty"),
                func.count(Order.id).label("cnt"),
            )
            .filter(
                Order.contract_id == contract_id,
                Order.side == side,
                Order.status.in_([OrderStatus.OPEN, OrderStatus.PARTIAL]),
            )
            .group_by(Order.price_per_share)
            .order_by(Order.price_per_share.asc() if asc else Order.price_per_share.desc())
            .limit(depth)
            .all()
        )
        return [
            {"price": r.price_per_share, "quantity": int(r.qty), "order_count": int(r.cnt)}
            for r in rows
        ]

    bids = levels(OrderSide.BID, asc=False)
    asks = levels(OrderSide.ASK, asc=True)
    return _summarise(bids, asks, contract_id)


# ── shared ────────────────────────────────────────────────────────────────────

def _summarise(bids: list, asks: list, contract_id) -> dict:
    best_bid = Decimal(str(bids[0]["price"])) if bids else None
    best_ask = Decimal(str(asks[0]["price"])) if asks else None
    spread = (best_ask - best_bid) if (best_bid is not None and best_ask is not None) else None
    mid = ((best_bid + best_ask) / 2) if (best_bid is not None and best_ask is not None) else None
    return {
        "contract_id": contract_id,
        "bids": bids,
        "asks": asks,
        "best_bid": best_bid,
        "best_ask": best_ask,
        "spread": spread,
        "mid_price": mid,
    }
