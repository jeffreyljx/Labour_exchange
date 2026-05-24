from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    # Imported only for static analysis — SQLAlchemy resolves string annotations
    # via its mapper registry at runtime, so no circular import at load time.
    from app.models.profile import Award, EducationEntry, EmploymentEntry, Skill, UserProfile
    from app.models.settlement import Distribution
    from app.models.trade import Trade

from sqlalchemy import Boolean, DateTime, Enum, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.models.base import Base


class VerificationStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class ReputationEventType(str, enum.Enum):
    MISSED_REPORT = "missed_report"
    LATE_REPORT = "late_report"
    DEFAULT = "default"
    PARTIAL_DEFAULT = "partial_default"


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    reputation_score: Mapped[float] = mapped_column(Float, default=100.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    credit_verification: Mapped["CreditVerification"] = relationship(back_populates="user", uselist=False)
    reputation_events: Mapped[list["ReputationEvent"]] = relationship(back_populates="user")
    contracts_issued: Mapped[list["Contract"]] = relationship(back_populates="issuer", foreign_keys="Contract.issuer_id")
    positions: Mapped[list["Position"]] = relationship(back_populates="holder")
    orders: Mapped[list["Order"]] = relationship(back_populates="user")

    # Trade history (buyer / seller side)
    buy_trades: Mapped[list["Trade"]] = relationship(
        foreign_keys="Trade.buyer_id", back_populates="buyer"
    )
    sell_trades: Mapped[list["Trade"]] = relationship(
        foreign_keys="Trade.seller_id", back_populates="seller"
    )

    # Income distributions received as a shareholder
    distributions_received: Mapped[list["Distribution"]] = relationship(back_populates="holder")

    # Profile / prospectus relationships
    profile: Mapped[Optional["UserProfile"]] = relationship(back_populates="user", uselist=False)
    educations: Mapped[list["EducationEntry"]] = relationship(back_populates="user")
    employments: Mapped[list["EmploymentEntry"]] = relationship(back_populates="user")
    awards: Mapped[list["Award"]] = relationship(back_populates="user")
    skills: Mapped[list["Skill"]] = relationship(back_populates="user")


class CreditVerification(Base):
    __tablename__ = "credit_verifications"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), unique=True, nullable=False)
    credit_score: Mapped[int] = mapped_column(Integer, nullable=False)
    ssn_last4: Mapped[str] = mapped_column(String(4), nullable=False)
    provider: Mapped[str] = mapped_column(String(50), default="mock")
    status: Mapped[VerificationStatus] = mapped_column(Enum(VerificationStatus), default=VerificationStatus.PENDING)
    verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped["User"] = relationship(back_populates="credit_verification")


class ReputationEvent(Base):
    __tablename__ = "reputation_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    contract_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("contracts.id"), nullable=True)
    event_type: Mapped[ReputationEventType] = mapped_column(Enum(ReputationEventType), nullable=False)
    penalty_points: Mapped[float] = mapped_column(Float, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped["User"] = relationship(back_populates="reputation_events")
