from __future__ import annotations

import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.settlement import IncomeReport, IncomeReportStatus
from app.models.user import User
from app.schemas.settlement import IncomeReportOut, IncomeReportSubmit
from app.services.security import get_current_user, require_verified
from app.services.settlement_service import submit_income_report

router = APIRouter(prefix="/settlement", tags=["settlement"])


@router.post("/reports", response_model=IncomeReportOut, status_code=201)
def submit_report(
    body: IncomeReportSubmit,
    current_user: User = Depends(require_verified),
    db: Session = Depends(get_db),
):
    """
    Submit quarterly gross income for one of your active contracts.

    The system auto-verifies the report and immediately computes
    distributions for all external shareholders.  Once distributed,
    a report cannot be resubmitted.
    """
    try:
        report = submit_income_report(
            issuer_id=current_user.id,
            contract_id=body.contract_id,
            period_start=body.period_start,
            period_end=body.period_end,
            gross_income=body.gross_income,
            db=db,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return report


@router.get("/reports", response_model=List[IncomeReportOut])
def list_my_reports(
    contract_id: Optional[uuid.UUID] = Query(default=None),
    report_status: Optional[IncomeReportStatus] = Query(default=None, alias="status"),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    current_user: User = Depends(require_verified),
    db: Session = Depends(get_db),
):
    """All income reports for contracts you issued."""
    q = db.query(IncomeReport).filter(IncomeReport.issuer_id == current_user.id)
    if contract_id:
        q = q.filter(IncomeReport.contract_id == contract_id)
    if report_status:
        q = q.filter(IncomeReport.status == report_status)
    return (
        q.order_by(IncomeReport.period_start.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )


@router.get("/reports/{report_id}", response_model=IncomeReportOut)
def get_report(
    report_id: uuid.UUID,
    current_user: User = Depends(require_verified),
    db: Session = Depends(get_db),
):
    """Detail view of a single income report (issuer only)."""
    report = (
        db.query(IncomeReport)
        .filter(
            IncomeReport.id == report_id,
            IncomeReport.issuer_id == current_user.id,
        )
        .first()
    )
    if not report:
        raise HTTPException(status_code=404, detail="Income report not found")
    return report
