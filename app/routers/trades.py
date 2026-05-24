from __future__ import annotations

import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.trade import Trade
from app.models.user import User
from app.schemas.trade import TradeOut
from app.services.security import get_current_user

router = APIRouter(prefix="/trades", tags=["trades"])


@router.get("/", response_model=List[TradeOut])
def my_trades(
    contract_id: Optional[uuid.UUID] = Query(default=None),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """All trades where the current user was the buyer or seller."""
    q = db.query(Trade).filter(
        (Trade.buyer_id == current_user.id) | (Trade.seller_id == current_user.id)
    )
    if contract_id:
        q = q.filter(Trade.contract_id == contract_id)
    return q.order_by(Trade.executed_at.desc()).offset(skip).limit(limit).all()


@router.get("/{trade_id}", response_model=TradeOut)
def get_trade(
    trade_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Fetch a single trade the current user was party to."""
    from fastapi import HTTPException
    trade = db.query(Trade).filter(
        Trade.id == trade_id,
        (Trade.buyer_id == current_user.id) | (Trade.seller_id == current_user.id),
    ).first()
    if not trade:
        raise HTTPException(status_code=404, detail="Trade not found")
    return trade
