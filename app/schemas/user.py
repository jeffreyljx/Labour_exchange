from __future__ import annotations

import re
from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, field_validator

from app.models.user import VerificationStatus


class UserRegisterRequest(BaseModel):
    email: str
    full_name: str
    password: str
    ssn_last4: str

    @field_validator("email")
    @classmethod
    def email_format(cls, v: str) -> str:
        if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", v):
            raise ValueError("Invalid email address")
        return v.lower()

    @field_validator("ssn_last4")
    @classmethod
    def ssn_format(cls, v: str) -> str:
        if not re.match(r"^\d{4}$", v):
            raise ValueError("ssn_last4 must be exactly 4 digits")
        return v

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        return v


class UserLoginRequest(BaseModel):
    email: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class CreditVerificationOut(BaseModel):
    credit_score: int
    status: VerificationStatus
    verified_at: Optional[datetime]

    model_config = {"from_attributes": True}


class UserOut(BaseModel):
    id: UUID
    email: str
    full_name: str
    is_verified: bool
    is_admin: bool = False
    reputation_score: float
    created_at: datetime

    model_config = {"from_attributes": True}


class UserProfileOut(UserOut):
    credit_verification: Optional[CreditVerificationOut]

    model_config = {"from_attributes": True}


class RegisterResponse(BaseModel):
    user: UserOut
    access_token: str
    token_type: str = "bearer"
