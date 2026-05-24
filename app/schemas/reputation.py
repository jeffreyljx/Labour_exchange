from __future__ import annotations

from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel

from app.models.user import ReputationEventType


class ReputationEventOut(BaseModel):
    id: UUID
    contract_id: Optional[UUID]
    event_type: ReputationEventType
    penalty_points: float   # positive = deduction; negative values reserved for future bonuses
    description: str
    created_at: datetime

    model_config = {"from_attributes": True}


class ReputationSummaryOut(BaseModel):
    """
    Public reputation record for a user — equivalent to a credit report
    on the exchange.  Buyers consult this before investing in a contract.
    """
    user_id: UUID
    full_name: str
    reputation_score: float    # 0–100; starts at 100
    total_events: int
    events: List[ReputationEventOut]
