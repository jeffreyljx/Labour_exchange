from __future__ import annotations

from datetime import date, datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, field_validator

from app.models.profile import AwardCategory, DataSource
from app.schemas.reputation import ReputationEventOut


# ── UserProfile ───────────────────────────────────────────────────────────────

class UserProfileUpdate(BaseModel):
    headline: Optional[str] = None
    bio: Optional[str] = None
    location: Optional[str] = None
    linkedin_url: Optional[str] = None


class UserProfileOut(BaseModel):
    id: UUID
    user_id: UUID
    headline: Optional[str]
    bio: Optional[str]
    location: Optional[str]
    linkedin_url: Optional[str]
    linkedin_imported_at: Optional[datetime]
    profile_completeness: float

    model_config = {"from_attributes": True}


# ── Education ─────────────────────────────────────────────────────────────────

class EducationCreate(BaseModel):
    institution: str
    degree: Optional[str] = None
    field_of_study: Optional[str] = None
    start_year: Optional[int] = None
    end_year: Optional[int] = None
    gpa: Optional[float] = None
    activities: Optional[str] = None
    description: Optional[str] = None
    is_current: bool = False

    @field_validator("gpa")
    @classmethod
    def gpa_range(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and not (0.0 <= v <= 4.0):
            raise ValueError("GPA must be between 0.0 and 4.0")
        return v


class EducationUpdate(EducationCreate):
    institution: Optional[str] = None  # all fields optional on update


class EducationOut(BaseModel):
    id: UUID
    institution: str
    degree: Optional[str]
    field_of_study: Optional[str]
    start_year: Optional[int]
    end_year: Optional[int]
    gpa: Optional[float]
    activities: Optional[str]
    description: Optional[str]
    is_current: bool
    source: DataSource

    model_config = {"from_attributes": True}


# ── Employment ────────────────────────────────────────────────────────────────

class EmploymentCreate(BaseModel):
    company: str
    title: str
    location: Optional[str] = None
    industry: Optional[str] = None
    description: Optional[str] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    is_current: bool = False


class EmploymentUpdate(EmploymentCreate):
    company: Optional[str] = None
    title: Optional[str] = None


class EmploymentOut(BaseModel):
    id: UUID
    company: str
    title: str
    location: Optional[str]
    industry: Optional[str]
    description: Optional[str]
    start_date: Optional[date]
    end_date: Optional[date]
    is_current: bool
    source: DataSource

    model_config = {"from_attributes": True}


# ── Awards ────────────────────────────────────────────────────────────────────

class AwardCreate(BaseModel):
    title: str
    issuer: Optional[str] = None
    date_issued: Optional[date] = None
    description: Optional[str] = None
    category: AwardCategory = AwardCategory.OTHER


class AwardOut(BaseModel):
    id: UUID
    title: str
    issuer: Optional[str]
    date_issued: Optional[date]
    description: Optional[str]
    category: AwardCategory
    source: DataSource

    model_config = {"from_attributes": True}


# ── Skills ────────────────────────────────────────────────────────────────────

class SkillCreate(BaseModel):
    name: str


class SkillsBatchCreate(BaseModel):
    skills: List[str]


class SkillOut(BaseModel):
    id: UUID
    name: str
    endorsement_count: int
    source: DataSource

    model_config = {"from_attributes": True}


# ── Composite public profile (what buyers see) ────────────────────────────────

class PublicProfileOut(BaseModel):
    """
    The 'prospectus' buyers read before investing in a human capital contract.
    Analogous to a company's 10-K filing on a stock exchange.
    """
    user_id: UUID
    full_name: str
    profile: Optional[UserProfileOut]
    education: List[EducationOut]
    employment: List[EmploymentOut]
    awards: List[AwardOut]
    skills: List[SkillOut]
    reputation_score: float
    profile_completeness: float
    recent_reputation_events: List[ReputationEventOut]  # last 5 events; public record

    model_config = {"from_attributes": True}


class LinkedInImportResult(BaseModel):
    education_imported: int
    employment_imported: int
    awards_imported: int
    skills_imported: int
    profile_completeness: float
