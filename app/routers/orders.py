from __future__ import annotations

import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.order import Order, OrderSide, OrderStatus
from app.models.user import User
from app.schemas.order import OrderCreate, OrderOut
from app.schemas.trade import OrderPlacementResult
from app.services.order_service import cancel_order, place_order
from app.services.security import get_current_user, require_verified

router = APIRouter(prefix="/orders", tags=["orders"])


@router.post("/", response_model=OrderPlacementResult, status_code=201)
def place(
    body: OrderCreate,
    current_user: User = Depends(require_verified),
    db: Session = Depends(get_db),
):
    try:
        order, trades = place_order(
            user_id=current_user.id,
            contract_id=body.contract_id,
            side=body.side,
            price_per_share=body.price_per_share,
            quantity=body.quantity,
            db=db,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    filled = sum(t.quantity for t in trades)
    remaining = order.quantity_remaining
    if filled == 0:
        message = "Order resting in book — no immediate fill."
    elif remaining == 0:
        message = f"Order fully filled across {len(trades)} trade(s)."
    else:
        message = f"Order partially filled ({filled} shares across {len(trades)} trade(s)); {remaining} shares resting."

    return OrderPlacementResult(
        order=order,
        fills=trades,
        filled_quantity=filled,
        remaining_quantity=remaining,
        message=message,
    )


@router.delete("/{order_id}", status_code=204)
def cancel(
    order_id: uuid.UUID,
    current_user: User = Depends(require_verified),
    db: Session = Depends(get_db),
):
    try:
        cancel_order(order_id, current_user.id, db)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/", response_model=List[OrderOut])
def list_my_orders(
    side: Optional[OrderSide] = Query(default=None),
    order_status: Optional[OrderStatus] = Query(default=None, alias="status"),
    contract_id: Optional[uuid.UUID] = Query(default=None),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    q = db.query(Order).filter(Order.user_id == current_user.id)
    if side:
        q = q.filter(Order.side == side)
    if order_status:
        q = q.filter(Order.status == order_status)
    if contract_id:
        q = q.filter(Order.contract_id == contract_id)
    return q.order_by(Order.created_at.desc()).offset(skip).limit(limit).all()


@router.get("/{order_id}", response_model=OrderOut)
def get_order(
    order_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    order = (
        db.query(Order)
        .filter(Order.id == order_id, Order.user_id == current_user.id)
        .first()
    )
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return order
