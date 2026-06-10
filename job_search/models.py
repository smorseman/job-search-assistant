"""Pydantic models for the canonical job schema and related types."""

from __future__ import annotations

import hashlib
import json
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, model_validator


class ATSTier(str, Enum):
    GREEN = "green"
    YELLOW = "yellow"
    RED = "red"
    UNKNOWN = "unknown"


class ATSType(str, Enum):
    GREENHOUSE = "greenhouse"
    LEVER = "lever"
    WORKDAY = "workday"
    SMARTRECRUITERS = "smartrecruiters"
    ASHBY = "ashby"
    WORKABLE = "workable"
    RECRUITEE = "recruitee"
    PERSONIO = "personio"
    ICIMS = "icims"
    TALEO = "taleo"
    SUCCESSFACTORS = "successfactors"
    NEOGOV = "neogov"
    USAJOBS = "usajobs"
    OTHER = "other"
    UNKNOWN = "unknown"


class AppState(str, Enum):
    DISCOVERED = "discovered"
    PRESENTED = "presented"
    SELECTED = "selected"
    APPLIED = "applied"
    ACKNOWLEDGED = "acknowledged"
    SCREEN = "screen"
    INTERVIEW = "interview"
    OFFER = "offer"
    REJECTED = "rejected"
    GHOSTED = "ghosted"


class StretchCategory(str, Enum):
    QUALIFIED = "qualified"
    COMPETITIVE_STRETCH = "competitive_stretch"
    LONG_SHOT = "long_shot"


class RemoteFlag(str, Enum):
    YES = "yes"
    NO = "no"
    HYBRID = "hybrid"
    UNKNOWN = "unknown"


class KnockoutFields(BaseModel):
    work_auth: str | None = None
    min_years: float | None = None
    eit_required: bool | None = None
    pe_required: bool | None = None
    clearance: str | None = None
    relocation: str | None = None
    degree_required: str | None = None       # e.g. "BS Civil Engineering"


class CanonicalJob(BaseModel):
    # Identifiers
    canonical_job_id: str = Field(default="")
    source: str
    source_job_id: str
    firm_id: str | None = None

    # Core fields
    company: str
    title: str
    discipline_tags: list[str] = Field(default_factory=list)
    location_city: str | None = None
    location_state: str | None = None
    location_country: str = "US"
    remote_flag: RemoteFlag = RemoteFlag.UNKNOWN

    # Content
    description_raw: str | None = None
    description_normalized: str | None = None
    jd_content_hash: str | None = None
    apply_url: str | None = None

    # Dates
    posted_date: str | None = None
    first_seen: str | None = None
    last_seen: str | None = None

    # Compensation
    salary_min: int | None = None
    salary_max: int | None = None

    # Parsed knockout fields
    knockout: KnockoutFields = Field(default_factory=KnockoutFields)

    # Scoring
    match_score: float | None = None
    stretch_category: StretchCategory | None = None
    benefit_score: float = 0.0
    career_trajectory_score: float = 0.0

    # State
    app_state: AppState = AppState.DISCOVERED
    ats_type: ATSType = ATSType.UNKNOWN

    @model_validator(mode="after")
    def compute_id_and_hash(self) -> CanonicalJob:
        if not self.canonical_job_id:
            raw = f"{self.source}:{self.source_job_id}"
            self.canonical_job_id = hashlib.sha256(raw.encode()).hexdigest()[:32]
        if self.description_normalized and not self.jd_content_hash:
            self.jd_content_hash = hashlib.md5(
                self.description_normalized.encode()
            ).hexdigest()
        return self

    def to_db_dict(self) -> dict[str, Any]:
        """Flatten to a dict matching the SQLite jobs table columns."""
        ko = self.knockout
        return {
            "canonical_job_id": self.canonical_job_id,
            "source": self.source,
            "source_job_id": self.source_job_id,
            "firm_id": self.firm_id,
            "company": self.company,
            "title": self.title,
            "discipline_tags": json.dumps(self.discipline_tags),
            "location_city": self.location_city,
            "location_state": self.location_state,
            "location_country": self.location_country,
            "remote_flag": self.remote_flag.value,
            "description_raw": self.description_raw,
            "description_normalized": self.description_normalized,
            "jd_content_hash": self.jd_content_hash,
            "apply_url": self.apply_url,
            "posted_date": self.posted_date,
            "salary_min": self.salary_min,
            "salary_max": self.salary_max,
            "ko_work_auth": ko.work_auth,
            "ko_min_years": ko.min_years,
            "ko_eit_required": int(ko.eit_required) if ko.eit_required is not None else None,
            "ko_pe_required": int(ko.pe_required) if ko.pe_required is not None else None,
            "ko_clearance": ko.clearance,
            "ko_relocation": ko.relocation,
            "ko_degree_required": ko.degree_required,
            "match_score": self.match_score,
            "stretch_category": self.stretch_category.value if self.stretch_category else None,
            "benefit_score": self.benefit_score,
            "career_trajectory_score": self.career_trajectory_score,
            "app_state": self.app_state.value,
            "ats_type": self.ats_type.value,
        }


class FirmConfig(BaseModel):
    """Config record for one employer in the registry (config-as-code)."""
    firm_id: str
    name: str
    website: str | None = None
    careers_url: str | None = None
    ats_type: ATSType = ATSType.UNKNOWN
    ats_tier: ATSTier = ATSTier.UNKNOWN
    ats_board_token: str | None = None      # Greenhouse / Lever
    ats_tenant: str | None = None           # Workday
    ats_site: str | None = None             # Workday
    default_filters: dict[str, Any] = Field(default_factory=dict)
    enr_rank: int | None = None
    employee_count: str | None = None
    specialties: list[str] = Field(default_factory=list)
    known_benefits: list[str] = Field(default_factory=list)
    tuition_reimbursement: bool = False
    pe_support: bool = False
    near_grad_programs: list[str] = Field(default_factory=list)
    reputation_notes: str | None = None
