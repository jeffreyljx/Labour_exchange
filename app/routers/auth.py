from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models.profile import UserProfile
from app.models.user import CreditVerification, User, VerificationStatus
from app.schemas.user import (
    RegisterResponse,
    TokenResponse,
    UserLoginRequest,
    UserProfileOut,
    UserRegisterRequest,
)
from app.services.credit_service import fetch_credit_score
from app.services.security import (
    create_access_token,
    get_current_user,
    hash_password,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=RegisterResponse, status_code=status.HTTP_201_CREATED)
def register(body: UserRegisterRequest, db: Session = Depends(get_db)):
    if db.query(User).filter(User.email == body.email).first():
        raise HTTPException(status_code=400, detail="Email already registered")

    user = User(
        email=body.email,
        full_name=body.full_name,
        password_hash=hash_password(body.password),
        is_active=True,
        is_verified=False,
    )
    db.add(user)
    db.flush()  # populate user.id without committing yet

    score = fetch_credit_score(body.ssn_last4)
    approved = score >= settings.min_credit_score

    credit = CreditVerification(
        user_id=user.id,
        credit_score=score,
        ssn_last4=body.ssn_last4,
        provider="mock",
        status=VerificationStatus.APPROVED if approved else VerificationStatus.REJECTED,
        verified_at=datetime.utcnow() if approved else None,
    )
    db.add(credit)

    if approved:
        user.is_verified = True
    else:
        user.is_active = False

    # Seed an empty profile so the user shows up in buyer searches immediately
    db.add(UserProfile(user_id=user.id))
    db.commit()
    db.refresh(user)

    if not approved:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                f"Credit score {score} is below the required minimum of "
                f"{settings.min_credit_score}. Account created but access denied."
            ),
        )

    token = create_access_token(str(user.id), user.email)
    return RegisterResponse(user=user, access_token=token)


@router.post("/login", response_model=TokenResponse)
def login(body: UserLoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == body.email).first()
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account is not active")
    if not user.is_verified:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account not verified")

    return TokenResponse(access_token=create_access_token(str(user.id), user.email))


@router.post("/dev-login", response_model=RegisterResponse)
def dev_login(db: Session = Depends(get_db)):
    """
    Prototype-only login that skips SSN/credit collection.

    This keeps the rest of the app using normal JWT/authenticated API calls
    while avoiding real identity data during local classroom demos.
    """
    if not settings.dev_auth_enabled:
        raise HTTPException(status_code=404, detail="Development login is disabled")

    email = "demo@hce.local"
    user = db.query(User).filter(User.email == email).first()
    if not user:
        user = User(
            email=email,
            full_name="Demo Trader",
            password_hash=hash_password("demo-password"),
            is_active=True,
            is_verified=True,
            reputation_score=100.0,
        )
        db.add(user)
        db.flush()
        db.add(CreditVerification(
            user_id=user.id,
            credit_score=700,
            ssn_last4="0000",
            provider="dev-bypass",
            status=VerificationStatus.APPROVED,
            verified_at=datetime.utcnow(),
        ))
        db.add(UserProfile(
            user_id=user.id,
            headline="Prototype account",
            bio="Development user for local demos.",
            profile_completeness=20.0,
        ))
    else:
        user.is_active = True
        user.is_verified = True
        if not db.query(UserProfile).filter(UserProfile.user_id == user.id).first():
            db.add(UserProfile(user_id=user.id))

    db.commit()
    db.refresh(user)
    token = create_access_token(str(user.id), user.email)
    return RegisterResponse(user=user, access_token=token)


@router.get("/me", response_model=UserProfileOut)
def me(current_user: User = Depends(get_current_user)):
    return current_user
