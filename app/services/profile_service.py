"""Shared logic for profile mutations — completeness scoring and upsert helpers."""
from __future__ import annotations

import uuid
from datetime import date
from typing import TYPE_CHECKING

from sqlalchemy.orm import Session

if TYPE_CHECKING:
    pass


def compute_and_save_completeness(user_id: uuid.UUID, db: Session) -> float:
    """
    Recompute the profile_completeness score (0–100) and persist it.

    Scoring rubric (mirrors what a buyer cares about before investing):
      Headline present          +10
      Bio present               +10
      Any education entry       +20
      Any employment entry      +20
      Any skill                 +10
      2+ years total experience +15
      Any award                 +15
                              ─────
      Max                       100
    """
    from app.models.profile import (
        Award, EducationEntry, EmploymentEntry, Skill, UserProfile,
    )

    profile = db.query(UserProfile).filter(UserProfile.user_id == user_id).first()
    if not profile:
        return 0.0

    educations = db.query(EducationEntry).filter(EducationEntry.user_id == user_id).all()
    employments = db.query(EmploymentEntry).filter(EmploymentEntry.user_id == user_id).all()
    awards = db.query(Award).filter(Award.user_id == user_id).all()
    skills = db.query(Skill).filter(Skill.user_id == user_id).all()

    score = 0.0
    if profile.headline:
        score += 10
    if profile.bio:
        score += 10
    if educations:
        score += 20
    if employments:
        score += 20
    if skills:
        score += 10
    if _total_experience_months(employments) >= 24:
        score += 15
    if awards:
        score += 15

    profile.profile_completeness = min(score, 100.0)
    db.add(profile)
    db.commit()
    return profile.profile_completeness


def _total_experience_months(employments: list) -> int:
    today = date.today()
    total = 0
    for emp in employments:
        if not emp.start_date:
            continue
        end = emp.end_date or today
        months = (end.year - emp.start_date.year) * 12 + (end.month - emp.start_date.month)
        total += max(0, months)
    return total
