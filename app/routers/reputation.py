from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.schemas.reputation import ReputationSummaryOut
from app.services.reputation_service import get_reputation_summary
from app.services.security import get_current_user

router = APIRouter(prefix="/reputation", tags=["reputation"])


@router.get("/me", response_model=ReputationSummaryOut)
def my_reputation(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Full reputation ledger for the authenticated user (last 50 events)."""
    return get_reputation_summary(current_user.id, db, limit=50)


@router.get("/{user_id}", response_model=ReputationSummaryOut)
def user_reputation(
    user_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Public reputation record for any user.
    Buyers use this to assess an issuer's track record before investing.
    """
    summary = get_reputation_summary(user_id, db, limit=20)
    if summary is None:
        raise HTTPException(status_code=404, detail="User not found")
    return summary
