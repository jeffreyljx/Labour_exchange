from __future__ import annotations

import uuid
from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.profile import (
    Award, AwardCategory, DataSource, EducationEntry,
    EmploymentEntry, Skill, UserProfile,
)
from app.models.user import User
from app.schemas.profile import (
    AwardCreate, AwardOut,
    EducationCreate, EducationOut, EducationUpdate,
    EmploymentCreate, EmploymentOut, EmploymentUpdate,
    LinkedInImportResult,
    PublicProfileOut,
    SkillCreate, SkillOut, SkillsBatchCreate,
    UserProfileOut, UserProfileUpdate,
)
from app.services.linkedin_parser import parse_linkedin_zip
from app.services.profile_service import compute_and_save_completeness
from app.services.security import get_current_user, require_verified

router = APIRouter(prefix="/profile", tags=["profile"])


# ── helpers ───────────────────────────────────────────────────────────────────

def _get_or_create_profile(user_id: uuid.UUID, db: Session) -> UserProfile:
    profile = db.query(UserProfile).filter(UserProfile.user_id == user_id).first()
    if not profile:
        profile = UserProfile(user_id=user_id)
        db.add(profile)
        db.commit()
        db.refresh(profile)
    return profile


def _build_public_profile(user: User, db: Session) -> dict:
    from app.models.profile import Award, EducationEntry, EmploymentEntry, Skill, UserProfile
    from app.models.user import ReputationEvent
    profile = db.query(UserProfile).filter(UserProfile.user_id == user.id).first()
    educations = db.query(EducationEntry).filter(EducationEntry.user_id == user.id).all()
    employments = db.query(EmploymentEntry).filter(EmploymentEntry.user_id == user.id).all()
    awards = db.query(Award).filter(Award.user_id == user.id).all()
    skills = db.query(Skill).filter(Skill.user_id == user.id).all()
    recent_events = (
        db.query(ReputationEvent)
        .filter(ReputationEvent.user_id == user.id)
        .order_by(ReputationEvent.created_at.desc())
        .limit(5)
        .all()
    )
    return {
        "user_id": user.id,
        "full_name": user.full_name,
        "profile": profile,
        "education": educations,
        "employment": employments,
        "awards": awards,
        "skills": skills,
        "reputation_score": user.reputation_score,
        "profile_completeness": profile.profile_completeness if profile else 0.0,
        "recent_reputation_events": recent_events,
    }


# ── own profile ───────────────────────────────────────────────────────────────

@router.get("/me", response_model=PublicProfileOut)
def get_my_profile(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _build_public_profile(current_user, db)


@router.put("/me", response_model=UserProfileOut)
def update_my_profile(
    body: UserProfileUpdate,
    current_user: User = Depends(require_verified),
    db: Session = Depends(get_db),
):
    profile = _get_or_create_profile(current_user.id, db)
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(profile, field, value)
    db.commit()
    db.refresh(profile)
    compute_and_save_completeness(current_user.id, db)
    db.refresh(profile)
    return profile


# ── public profile (buyer view) ───────────────────────────────────────────────

@router.get("/{user_id}", response_model=PublicProfileOut)
def get_public_profile(
    user_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.id == user_id, User.is_active == True).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return _build_public_profile(user, db)


# ── education ─────────────────────────────────────────────────────────────────

@router.post("/education", response_model=EducationOut, status_code=201)
def add_education(
    body: EducationCreate,
    current_user: User = Depends(require_verified),
    db: Session = Depends(get_db),
):
    entry = EducationEntry(**body.model_dump(), user_id=current_user.id)
    db.add(entry)
    db.commit()
    db.refresh(entry)
    compute_and_save_completeness(current_user.id, db)
    return entry


@router.put("/education/{entry_id}", response_model=EducationOut)
def update_education(
    entry_id: uuid.UUID,
    body: EducationUpdate,
    current_user: User = Depends(require_verified),
    db: Session = Depends(get_db),
):
    entry = db.query(EducationEntry).filter(
        EducationEntry.id == entry_id, EducationEntry.user_id == current_user.id
    ).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Education entry not found")
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(entry, field, value)
    db.commit()
    db.refresh(entry)
    return entry


@router.delete("/education/{entry_id}", status_code=204)
def delete_education(
    entry_id: uuid.UUID,
    current_user: User = Depends(require_verified),
    db: Session = Depends(get_db),
):
    entry = db.query(EducationEntry).filter(
        EducationEntry.id == entry_id, EducationEntry.user_id == current_user.id
    ).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Education entry not found")
    db.delete(entry)
    db.commit()
    compute_and_save_completeness(current_user.id, db)


# ── employment ────────────────────────────────────────────────────────────────

@router.post("/employment", response_model=EmploymentOut, status_code=201)
def add_employment(
    body: EmploymentCreate,
    current_user: User = Depends(require_verified),
    db: Session = Depends(get_db),
):
    entry = EmploymentEntry(**body.model_dump(), user_id=current_user.id)
    db.add(entry)
    db.commit()
    db.refresh(entry)
    compute_and_save_completeness(current_user.id, db)
    return entry


@router.put("/employment/{entry_id}", response_model=EmploymentOut)
def update_employment(
    entry_id: uuid.UUID,
    body: EmploymentUpdate,
    current_user: User = Depends(require_verified),
    db: Session = Depends(get_db),
):
    entry = db.query(EmploymentEntry).filter(
        EmploymentEntry.id == entry_id, EmploymentEntry.user_id == current_user.id
    ).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Employment entry not found")
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(entry, field, value)
    db.commit()
    db.refresh(entry)
    return entry


@router.delete("/employment/{entry_id}", status_code=204)
def delete_employment(
    entry_id: uuid.UUID,
    current_user: User = Depends(require_verified),
    db: Session = Depends(get_db),
):
    entry = db.query(EmploymentEntry).filter(
        EmploymentEntry.id == entry_id, EmploymentEntry.user_id == current_user.id
    ).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Employment entry not found")
    db.delete(entry)
    db.commit()
    compute_and_save_completeness(current_user.id, db)


# ── awards ────────────────────────────────────────────────────────────────────

@router.post("/awards", response_model=AwardOut, status_code=201)
def add_award(
    body: AwardCreate,
    current_user: User = Depends(require_verified),
    db: Session = Depends(get_db),
):
    award = Award(**body.model_dump(), user_id=current_user.id)
    db.add(award)
    db.commit()
    db.refresh(award)
    compute_and_save_completeness(current_user.id, db)
    return award


@router.delete("/awards/{award_id}", status_code=204)
def delete_award(
    award_id: uuid.UUID,
    current_user: User = Depends(require_verified),
    db: Session = Depends(get_db),
):
    award = db.query(Award).filter(
        Award.id == award_id, Award.user_id == current_user.id
    ).first()
    if not award:
        raise HTTPException(status_code=404, detail="Award not found")
    db.delete(award)
    db.commit()
    compute_and_save_completeness(current_user.id, db)


# ── skills ────────────────────────────────────────────────────────────────────

@router.post("/skills", response_model=SkillOut, status_code=201)
def add_skill(
    body: SkillCreate,
    current_user: User = Depends(require_verified),
    db: Session = Depends(get_db),
):
    existing = db.query(Skill).filter(
        Skill.user_id == current_user.id, Skill.name == body.name
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="Skill already exists")
    skill = Skill(user_id=current_user.id, name=body.name)
    db.add(skill)
    db.commit()
    db.refresh(skill)
    compute_and_save_completeness(current_user.id, db)
    return skill


@router.post("/skills/batch", response_model=List[SkillOut], status_code=201)
def add_skills_batch(
    body: SkillsBatchCreate,
    current_user: User = Depends(require_verified),
    db: Session = Depends(get_db),
):
    added = []
    for name in body.skills:
        name = name.strip()
        if not name:
            continue
        if db.query(Skill).filter(Skill.user_id == current_user.id, Skill.name == name).first():
            continue
        skill = Skill(user_id=current_user.id, name=name)
        db.add(skill)
        added.append(skill)
    db.commit()
    for s in added:
        db.refresh(s)
    compute_and_save_completeness(current_user.id, db)
    return added


@router.delete("/skills/{skill_id}", status_code=204)
def delete_skill(
    skill_id: uuid.UUID,
    current_user: User = Depends(require_verified),
    db: Session = Depends(get_db),
):
    skill = db.query(Skill).filter(
        Skill.id == skill_id, Skill.user_id == current_user.id
    ).first()
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")
    db.delete(skill)
    db.commit()
    compute_and_save_completeness(current_user.id, db)


# ── LinkedIn import ───────────────────────────────────────────────────────────

@router.post("/import/linkedin", response_model=LinkedInImportResult)
async def import_linkedin(
    file: UploadFile = File(...),
    current_user: User = Depends(require_verified),
    db: Session = Depends(get_db),
):
    if not file.filename or not file.filename.endswith(".zip"):
        raise HTTPException(status_code=422, detail="Please upload a .zip LinkedIn data export")

    raw = await file.read()
    try:
        data = parse_linkedin_zip(raw)
    except Exception:
        raise HTTPException(status_code=422, detail="Could not parse LinkedIn ZIP. Ensure it is an unmodified LinkedIn data export.")

    # Update or create profile
    profile = _get_or_create_profile(current_user.id, db)
    for field, value in data["profile"].items():
        if value is not None:
            setattr(profile, field, value)
    profile.linkedin_imported_at = datetime.utcnow()
    db.add(profile)

    # Replace all LinkedIn-sourced entries (re-import is idempotent)
    db.query(EducationEntry).filter(
        EducationEntry.user_id == current_user.id,
        EducationEntry.source == DataSource.LINKEDIN,
    ).delete()
    db.query(EmploymentEntry).filter(
        EmploymentEntry.user_id == current_user.id,
        EmploymentEntry.source == DataSource.LINKEDIN,
    ).delete()
    db.query(Award).filter(
        Award.user_id == current_user.id,
        Award.source == DataSource.LINKEDIN,
    ).delete()
    db.query(Skill).filter(
        Skill.user_id == current_user.id,
        Skill.source == DataSource.LINKEDIN,
    ).delete()
    db.flush()

    for row in data["education"]:
        db.add(EducationEntry(user_id=current_user.id, **row))

    for row in data["employment"]:
        db.add(EmploymentEntry(user_id=current_user.id, **row))

    for row in data["awards"]:
        row["category"] = AwardCategory(row.get("category", "other"))
        row["source"] = DataSource.LINKEDIN
        row.pop("source", None)
        db.add(Award(user_id=current_user.id, **row))

    seen_skills: set = set()
    for row in data["skills"]:
        name = row["name"]
        if name in seen_skills:
            continue
        seen_skills.add(name)
        existing = db.query(Skill).filter(
            Skill.user_id == current_user.id, Skill.name == name
        ).first()
        if not existing:
            db.add(Skill(user_id=current_user.id, **row))

    db.commit()
    completeness = compute_and_save_completeness(current_user.id, db)

    return LinkedInImportResult(
        education_imported=len(data["education"]),
        employment_imported=len(data["employment"]),
        awards_imported=len(data["awards"]),
        skills_imported=len(seen_skills),
        profile_completeness=completeness,
    )
