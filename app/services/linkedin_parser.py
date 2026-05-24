"""
LinkedIn data export parser.

Users download their data from linkedin.com/settings -> Data Privacy
-> Get a copy of your data. This produces a ZIP with CSV files.
We consume: Profile.csv, Education.csv, Positions.csv, Honors.csv, Skills.csv.
"""
from __future__ import annotations

import calendar
import csv
import io
import zipfile
from datetime import date
from typing import Optional


def parse_linkedin_zip(zip_bytes: bytes) -> dict:
    """Return a structured dict ready to be upserted into the profile tables."""
    result: dict = {
        "profile": {},
        "education": [],
        "employment": [],
        "awards": [],
        "skills": [],
    }

    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        names = set(zf.namelist())

        if "Profile.csv" in names:
            with zf.open("Profile.csv") as f:
                reader = csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig"))
                for row in reader:
                    result["profile"] = {
                        "headline": _clean(row.get("Headline")),
                        "bio": _clean(row.get("Summary")),
                        "location": _clean(row.get("Geo Location") or row.get("Address")),
                    }
                    break  # one row only

        if "Education.csv" in names:
            with zf.open("Education.csv") as f:
                reader = csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig"))
                for row in reader:
                    institution = _clean(row.get("School Name"))
                    if not institution:
                        continue
                    end_raw = _clean(row.get("End Date"))
                    result["education"].append({
                        "institution": institution,
                        "degree": _clean(row.get("Degree Name")),
                        "field_of_study": _clean(row.get("Notes")),
                        "activities": _clean(row.get("Activities")),
                        "start_year": _parse_year(row.get("Start Date")),
                        "end_year": _parse_year(end_raw),
                        "is_current": not bool(end_raw),
                        "source": "linkedin",
                    })

        if "Positions.csv" in names:
            with zf.open("Positions.csv") as f:
                reader = csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig"))
                for row in reader:
                    company = _clean(row.get("Company Name"))
                    title = _clean(row.get("Title"))
                    if not company or not title:
                        continue
                    end_raw = _clean(row.get("Finished On"))
                    result["employment"].append({
                        "company": company,
                        "title": title,
                        "description": _clean(row.get("Description")),
                        "location": _clean(row.get("Location")),
                        "start_date": _parse_date(row.get("Started On")),
                        "end_date": _parse_date(end_raw),
                        "is_current": not bool(end_raw),
                        "source": "linkedin",
                    })

        # LinkedIn uses different filenames across export versions
        for honors_file in ("Honors.csv", "Honor_Awards.csv"):
            if honors_file in names:
                with zf.open(honors_file) as f:
                    reader = csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig"))
                    for row in reader:
                        title = _clean(row.get("Title"))
                        if not title:
                            continue
                        result["awards"].append({
                            "title": title,
                            "issuer": _clean(row.get("Issuer")),
                            "date_issued": _parse_date(row.get("Issued On")),
                            "description": _clean(row.get("Description")),
                            "category": "other",
                            "source": "linkedin",
                        })
                break

        if "Skills.csv" in names:
            with zf.open("Skills.csv") as f:
                reader = csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig"))
                for row in reader:
                    name = _clean(row.get("Name"))
                    if name:
                        result["skills"].append({
                            "name": name,
                            "endorsement_count": 0,
                            "source": "linkedin",
                        })

    return result


# ── helpers ──────────────────────────────────────────────────────────────────

_MONTH_ABBR = {m.lower(): i for i, m in enumerate(calendar.month_abbr) if m}


def _clean(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    v = value.strip()
    return v if v else None


def _parse_year(s: Optional[str]) -> Optional[int]:
    """Extract a 4-digit year from strings like 'May 2020', '2020', 'Aug 2019'."""
    if not s:
        return None
    for part in reversed(s.strip().split()):
        if part.isdigit() and len(part) == 4:
            return int(part)
    return None


def _parse_date(s: Optional[str]) -> Optional[date]:
    """Parse LinkedIn date strings ('Jan 2020', '2020') into a date object."""
    if not s or not s.strip():
        return None
    parts = s.strip().split()
    try:
        if len(parts) == 2:
            month = _MONTH_ABBR.get(parts[0][:3].lower(), 1)
            return date(int(parts[1]), month, 1)
        if len(parts) == 1 and parts[0].isdigit():
            return date(int(parts[0]), 1, 1)
    except (ValueError, KeyError):
        pass
    return None
