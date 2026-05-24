from __future__ import annotations

import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.contract import Contract, ContractStatus
from app.models.position import Position
from app.models.profile import UserProfile
from app.models.user import User
from app.models.order import OrderSide
from app.schemas.contract import (
    BuybackRequest,
    ContractCreate,
    ContractDetailOut,
    ContractOut,
    ContractUpdate,
    IssuanceCapacityOut,
    IssuerSummaryOut,
)
from app.schemas.order import OrderBookOut, OrderOut
from app.schemas.settlement import IncomeReportOut
from app.schemas.trade import OrderPlacementResult, TradeOut
from app.services.contract_service import (
    activate_contract,
    check_issuance_capacity,
    expire_overdue,
    get_total_issued_pct,
)
from app.services.order_book import get_book_from_db, get_book_from_redis
from app.services.order_service import place_order
from app.services.security import get_current_user, require_verified

router = APIRouter(prefix="/contracts", tags=["contracts"])


# ── helpers ───────────────────────────────────────────────────────────────────

def _issuer_summary(issuer: User, db: Session) -> IssuerSummaryOut:
    profile = db.query(UserProfile).filter(UserProfile.user_id == issuer.id).first()
    return IssuerSummaryOut(
        id=issuer.id,
        full_name=issuer.full_name,
        reputation_score=issuer.reputation_score,
        profile_completeness=profile.profile_completeness if profile else 0.0,
        headline=profile.headline if profile else None,
    )


def _position_counts(contract: Contract, db: Session) -> tuple:
    """Returns (shares_held_by_issuer, shares_in_circulation)."""
    issuer_pos = db.query(Position).filter(
        Position.contract_id == contract.id,
        Position.holder_id == contract.issuer_id,
    ).first()
    held_by_issuer = issuer_pos.shares_held if issuer_pos else 0
    return held_by_issuer, contract.total_shares - held_by_issuer


def _build_detail(contract: Contract, db: Session) -> dict:
    held, circulation = _position_counts(contract, db)
    return {
        **ContractOut.model_validate(contract).model_dump(),
        "issuer": _issuer_summary(contract.issuer, db),
        "shares_held_by_issuer": held,
        "shares_in_circulation": circulation,
    }


# ── issuance capacity ─────────────────────────────────────────────────────────

@router.get("/capacity", response_model=IssuanceCapacityOut)
def my_issuance_capacity(
    current_user: User = Depends(require_verified),
    db: Session = Depends(get_db),
):
    """How much of the 49 % cap has this issuer already used."""
    total = get_total_issued_pct(current_user.id, db)
    return IssuanceCapacityOut(
        total_pct_issued=total,
        remaining_pct=max(0.0, 49.0 - total),
    )


# ── create ────────────────────────────────────────────────────────────────────

@router.post("/", response_model=ContractOut, status_code=201)
def create_contract(
    body: ContractCreate,
    current_user: User = Depends(require_verified),
    db: Session = Depends(get_db),
):
    if not check_issuance_capacity(current_user.id, body.income_pct, db):
        total = get_total_issued_pct(current_user.id, db)
        raise HTTPException(
            status_code=400,
            detail=(
                f"Cannot create contract: {body.income_pct}% would push your total "
                f"issuance to {total + body.income_pct:.2f}%, exceeding the 49% cap. "
                f"You have {max(0.0, 49.0 - total):.2f}% remaining."
            ),
        )

    contract = Contract(
        issuer_id=current_user.id,
        title=body.title,
        description=body.description,
        income_pct=body.income_pct,
        term_years=body.term_years,
        ipo_price_per_share=body.ipo_price_per_share,
    )
    db.add(contract)
    db.commit()
    db.refresh(contract)
    return contract


# ── activate ──────────────────────────────────────────────────────────────────

@router.post("/{contract_id}/activate", response_model=ContractDetailOut)
def activate(
    contract_id: uuid.UUID,
    current_user: User = Depends(require_verified),
    db: Session = Depends(get_db),
):
    contract = db.query(Contract).filter(
        Contract.id == contract_id,
        Contract.issuer_id == current_user.id,
    ).first()
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")

    try:
        activate_contract(contract, db)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return _build_detail(contract, db)


# ── browse market ─────────────────────────────────────────────────────────────

@router.get("/", response_model=List[ContractOut])
def list_contracts(
    contract_status: Optional[ContractStatus] = Query(default=ContractStatus.ACTIVE),
    issuer_id: Optional[uuid.UUID] = Query(default=None),
    min_pct: Optional[float] = Query(default=None, ge=0, le=49),
    max_pct: Optional[float] = Query(default=None, ge=0, le=49),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # Lazily expire any overdue contracts before returning results
    expire_overdue(db)

    q = db.query(Contract)
    if contract_status:
        q = q.filter(Contract.status == contract_status)
    if issuer_id:
        q = q.filter(Contract.issuer_id == issuer_id)
    if min_pct is not None:
        q = q.filter(Contract.income_pct >= min_pct)
    if max_pct is not None:
        q = q.filter(Contract.income_pct <= max_pct)

    return q.order_by(Contract.created_at.desc()).offset(skip).limit(limit).all()


# ── my contracts ──────────────────────────────────────────────────────────────

@router.get("/mine", response_model=List[ContractOut])
def my_contracts(
    current_user: User = Depends(require_verified),
    db: Session = Depends(get_db),
):
    expire_overdue(db)
    return (
        db.query(Contract)
        .filter(Contract.issuer_id == current_user.id)
        .order_by(Contract.created_at.desc())
        .all()
    )


# ── detail ────────────────────────────────────────────────────────────────────

@router.get("/{contract_id}", response_model=ContractDetailOut)
def get_contract(
    contract_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    expire_overdue(db)
    contract = db.query(Contract).filter(Contract.id == contract_id).first()
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")
    return _build_detail(contract, db)


# ── update (DRAFT only) ───────────────────────────────────────────────────────

@router.patch("/{contract_id}", response_model=ContractOut)
def update_contract(
    contract_id: uuid.UUID,
    body: ContractUpdate,
    current_user: User = Depends(require_verified),
    db: Session = Depends(get_db),
):
    contract = db.query(Contract).filter(
        Contract.id == contract_id,
        Contract.issuer_id == current_user.id,
    ).first()
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")
    if contract.status != ContractStatus.DRAFT:
        raise HTTPException(status_code=400, detail="Only DRAFT contracts can be edited")

    updates = body.model_dump(exclude_none=True)

    # Re-check cap if income_pct is being changed
    if "income_pct" in updates:
        if not check_issuance_capacity(
            current_user.id, updates["income_pct"], db, exclude_id=contract.id
        ):
            total = get_total_issued_pct(current_user.id, db, exclude_id=contract.id)
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Updated income_pct {updates['income_pct']}% would push total to "
                    f"{total + updates['income_pct']:.2f}%, exceeding the 49% cap."
                ),
            )

    for field, value in updates.items():
        setattr(contract, field, value)

    db.commit()
    db.refresh(contract)
    return contract


# ── delete (DRAFT only) ───────────────────────────────────────────────────────

@router.delete("/{contract_id}", status_code=204)
def delete_contract(
    contract_id: uuid.UUID,
    current_user: User = Depends(require_verified),
    db: Session = Depends(get_db),
):
    contract = db.query(Contract).filter(
        Contract.id == contract_id,
        Contract.issuer_id == current_user.id,
    ).first()
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")
    if contract.status != ContractStatus.DRAFT:
        raise HTTPException(status_code=400, detail="Only DRAFT contracts can be deleted")

    db.delete(contract)
    db.commit()


# ── issuer buyback ────────────────────────────────────────────────────────────

@router.post("/{contract_id}/buyback", response_model=OrderPlacementResult, status_code=201)
def buyback(
    contract_id: uuid.UUID,
    body: BuybackRequest,
    current_user: User = Depends(require_verified),
    db: Session = Depends(get_db),
):
    """
    Issuer places a bid to repurchase shares from the open market.

    The bid enters the order book at the requested price. If a holder has
    an open ask at or below that price, the matching engine executes the
    trade immediately; otherwise the bid rests in the book until a seller
    accepts it.
    """
    contract = db.query(Contract).filter(
        Contract.id == contract_id,
        Contract.issuer_id == current_user.id,
        Contract.status == ContractStatus.ACTIVE,
    ).first()
    if not contract:
        raise HTTPException(
            status_code=404,
            detail="Active contract not found or you are not the issuer",
        )

    issuer_pos = db.query(Position).filter(
        Position.contract_id == contract_id,
        Position.holder_id == current_user.id,
    ).first()
    held_by_issuer = issuer_pos.shares_held if issuer_pos else 0
    in_circulation = contract.total_shares - held_by_issuer

    if body.quantity > in_circulation:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Cannot bid for {body.quantity} shares — only "
                f"{in_circulation} are currently held by third-party investors"
            ),
        )

    try:
        order, trades = place_order(
            user_id=current_user.id,
            contract_id=contract_id,
            side=OrderSide.BID,
            price_per_share=body.price_per_share,
            quantity=body.quantity,
            db=db,
            is_buyback=True,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    filled = sum(t.quantity for t in trades)
    remaining = order.quantity_remaining
    if filled == 0:
        message = "Buyback bid resting in book — no sellers matched at this price."
    elif remaining == 0:
        message = f"Buyback fully executed across {len(trades)} trade(s)."
    else:
        message = f"Buyback partially filled ({filled} shares); {remaining} shares resting."

    return OrderPlacementResult(
        order=order,
        fills=trades,
        filled_quantity=filled,
        remaining_quantity=remaining,
        message=message,
    )


# ── contract trade history ────────────────────────────────────────────────────

@router.get("/{contract_id}/trades", response_model=List[TradeOut])
def contract_trades(
    contract_id: uuid.UUID,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Public trade history for a contract, newest first."""
    from app.models.trade import Trade
    contract = db.query(Contract).filter(Contract.id == contract_id).first()
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")

    return (
        db.query(Trade)
        .filter(Trade.contract_id == contract_id)
        .order_by(Trade.executed_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )


# ── income report history (public) ───────────────────────────────────────────

@router.get("/{contract_id}/reports", response_model=List[IncomeReportOut])
def contract_reports(
    contract_id: uuid.UUID,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Public income-report history for a contract, newest period first."""
    from app.models.settlement import IncomeReport
    contract = db.query(Contract).filter(Contract.id == contract_id).first()
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")
    return (
        db.query(IncomeReport)
        .filter(IncomeReport.contract_id == contract_id)
        .order_by(IncomeReport.period_start.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )


# ── live order book ───────────────────────────────────────────────────────────

@router.get("/{contract_id}/orderbook", response_model=OrderBookOut)
def get_orderbook(
    contract_id: uuid.UUID,
    depth: int = Query(default=10, ge=1, le=50),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Returns aggregated bid/ask levels for a contract.
    Served from Redis when available; falls back to a live Postgres aggregate.
    """
    contract = db.query(Contract).filter(Contract.id == contract_id).first()
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")

    book = get_book_from_redis(str(contract_id), depth)
    if book is None:
        book = get_book_from_db(contract_id, depth, db)

    return book
