from __future__ import annotations

import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.schemas.portfolio import DistributionOut, HoldingOut, PortfolioSummaryOut
from app.services.portfolio_service import (
    get_distributions,
    get_holding,
    get_holdings,
    get_portfolio_summary,
)
from app.services.security import get_current_user

router = APIRouter(prefix="/portfolio", tags=["portfolio"])


@router.get("/summary", response_model=PortfolioSummaryOut)
def summary(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Aggregate P&L and lifetime distribution totals across all open positions."""
    return get_portfolio_summary(current_user.id, db)


@router.get("/holdings", response_model=List[HoldingOut])
def holdings(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """All contracts the current user currently holds shares in, with P&L."""
    return get_holdings(current_user.id, db)


@router.get("/holdings/{contract_id}", response_model=HoldingOut)
def holding_detail(
    contract_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """P&L detail for a single contract position."""
    h = get_holding(current_user.id, contract_id, db)
    if h is None:
        raise HTTPException(status_code=404, detail="No active position in this contract")
    return h


@router.get("/distributions", response_model=List[DistributionOut])
def distributions(
    contract_id: Optional[uuid.UUID] = Query(default=None),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Quarterly income distribution payouts received by the current user."""
    return get_distributions(
        current_user.id, db,
        contract_id=contract_id,
        skip=skip,
        limit=limit,
    )
