from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.contract import Contract, ContractStatus
from app.models.settlement import IncomeReport, IncomeReportStatus
from app.models.trade import Trade
from app.models.user import User
from app.services.security import require_admin

router = APIRouter(prefix="/admin", tags=["admin"])


# ── Response schemas ──────────────────────────────────────────────────────────

class PlatformStatsOut(BaseModel):
    total_users: int
    verified_users: int
    active_users: int
    suspended_users: int
    active_contracts: int
    draft_contracts: int
    total_volume_30d: str
    total_trades_30d: int
    overdue_reports: int


class AdminUserOut(BaseModel):
    id: UUID
    email: str
    full_name: str
    is_active: bool
    is_verified: bool
    is_admin: bool
    reputation_score: float
    created_at: datetime

    model_config = {"from_attributes": True}


class AdminContractOut(BaseModel):
    id: UUID
    issuer_id: UUID
    issuer_name: str
    title: str
    income_pct: float
    term_years: int
    total_shares: int
    status: str
    ipo_price_per_share: str
    last_price: Optional[str]
    created_at: datetime

    model_config = {"from_attributes": True}


class AdminIncomeReportOut(BaseModel):
    id: UUID
    contract_id: UUID
    contract_title: str
    issuer_id: UUID
    issuer_name: str
    period_end: str
    due_date: str
    status: str
    submitted_at: Optional[datetime]

    model_config = {"from_attributes": True}


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/stats", response_model=PlatformStatsOut)
def get_platform_stats(db: Session = Depends(get_db), _=Depends(require_admin)):
    cutoff = datetime.utcnow() - timedelta(days=30)

    total_users     = db.query(func.count(User.id)).scalar() or 0
    verified_users  = db.query(func.count(User.id)).filter(User.is_verified == True).scalar() or 0
    active_users    = db.query(func.count(User.id)).filter(User.is_active == True).scalar() or 0
    suspended_users = db.query(func.count(User.id)).filter(User.is_active == False).scalar() or 0

    active_contracts = db.query(func.count(Contract.id)).filter(Contract.status == ContractStatus.ACTIVE).scalar() or 0
    draft_contracts  = db.query(func.count(Contract.id)).filter(Contract.status == ContractStatus.DRAFT).scalar() or 0

    recent_trades = db.query(Trade).filter(Trade.executed_at >= cutoff).all()
    total_volume_30d = sum(float(t.total_value) for t in recent_trades)
    total_trades_30d = len(recent_trades)

    overdue_reports = db.query(func.count(IncomeReport.id)).filter(
        IncomeReport.status == IncomeReportStatus.OVERDUE
    ).scalar() or 0

    return PlatformStatsOut(
        total_users=total_users,
        verified_users=verified_users,
        active_users=active_users,
        suspended_users=suspended_users,
        active_contracts=active_contracts,
        draft_contracts=draft_contracts,
        total_volume_30d=f"{total_volume_30d:.2f}",
        total_trades_30d=total_trades_30d,
        overdue_reports=overdue_reports,
    )


@router.get("/users", response_model=List[AdminUserOut])
def list_users(
    search: Optional[str] = Query(None, description="Filter by name or email substring"),
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db),
    _=Depends(require_admin),
):
    q = db.query(User)
    if search:
        pattern = f"%{search}%"
        q = q.filter((User.email.ilike(pattern)) | (User.full_name.ilike(pattern)))
    return q.order_by(User.created_at.desc()).offset(skip).limit(limit).all()


@router.patch("/users/{user_id}/active", response_model=AdminUserOut)
def toggle_user_active(
    user_id: UUID,
    db: Session = Depends(get_db),
    admin=Depends(require_admin),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.id == admin.id:
        raise HTTPException(status_code=400, detail="Cannot suspend your own account")
    user.is_active = not user.is_active
    db.commit()
    db.refresh(user)
    return user


@router.get("/contracts", response_model=List[AdminContractOut])
def list_all_contracts(
    status_filter: Optional[str] = Query(None, alias="status"),
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db),
    _=Depends(require_admin),
):
    q = db.query(Contract)
    if status_filter:
        try:
            q = q.filter(Contract.status == ContractStatus(status_filter.lower()))
        except ValueError:
            pass
    contracts = q.order_by(Contract.created_at.desc()).offset(skip).limit(limit).all()

    result = []
    for c in contracts:
        result.append(AdminContractOut(
            id=c.id,
            issuer_id=c.issuer_id,
            issuer_name=c.issuer.full_name if c.issuer else "—",
            title=c.title,
            income_pct=c.income_pct,
            term_years=c.term_years,
            total_shares=c.total_shares,
            status=c.status.value,
            ipo_price_per_share=str(c.ipo_price_per_share),
            last_price=str(c.last_price) if c.last_price else None,
            created_at=c.created_at,
        ))
    return result


@router.patch("/contracts/{contract_id}/expire", response_model=AdminContractOut)
def force_expire_contract(
    contract_id: UUID,
    db: Session = Depends(get_db),
    _=Depends(require_admin),
):
    contract = db.query(Contract).filter(Contract.id == contract_id).first()
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")
    if contract.status not in (ContractStatus.ACTIVE, ContractStatus.DRAFT):
        raise HTTPException(status_code=400, detail=f"Cannot expire a contract in {contract.status.value} state")
    contract.status = ContractStatus.EXPIRED
    db.commit()
    db.refresh(contract)
    return AdminContractOut(
        id=contract.id,
        issuer_id=contract.issuer_id,
        issuer_name=contract.issuer.full_name if contract.issuer else "—",
        title=contract.title,
        income_pct=contract.income_pct,
        term_years=contract.term_years,
        total_shares=contract.total_shares,
        status=contract.status.value,
        ipo_price_per_share=str(contract.ipo_price_per_share),
        last_price=str(contract.last_price) if contract.last_price else None,
        created_at=contract.created_at,
    )


@router.get("/settlement/overdue", response_model=List[AdminIncomeReportOut])
def list_overdue_reports(
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db),
    _=Depends(require_admin),
):
    reports = (
        db.query(IncomeReport)
        .filter(IncomeReport.status == IncomeReportStatus.OVERDUE)
        .order_by(IncomeReport.due_date)
        .offset(skip)
        .limit(limit)
        .all()
    )

    result = []
    for r in reports:
        contract = db.query(Contract).filter(Contract.id == r.contract_id).first()
        issuer   = db.query(User).filter(User.id == r.issuer_id).first()
        result.append(AdminIncomeReportOut(
            id=r.id,
            contract_id=r.contract_id,
            contract_title=contract.title if contract else "—",
            issuer_id=r.issuer_id,
            issuer_name=issuer.full_name if issuer else "—",
            period_end=str(r.period_end),
            due_date=str(r.due_date),
            status=r.status.value,
            submitted_at=r.submitted_at if hasattr(r, "submitted_at") else None,
        ))
    return result
