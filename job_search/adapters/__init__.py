# Map ATS types → adapter classes for the ingestor's per-firm dispatch.
# (USAJOBS, Adzuna, email alerts have no firm — handled separately in the ingestor.)
from job_search.models import ATSType

from .adzuna import AdzunaAdapter
from .ashby import AshbyAdapter
from .base import BaseAdapter
from .email_alerts import EmailAlertsAdapter
from .greenhouse import GreenhouseAdapter
from .lever import LeverAdapter
from .recruitee import RecruiteeAdapter
from .smartrecruiters import SmartRecruitersAdapter
from .usajobs import USAJobsAdapter
from .workable import WorkableAdapter
from .workday import WorkdayAdapter

ATS_ADAPTER_MAP = {
    ATSType.GREENHOUSE:      GreenhouseAdapter,
    ATSType.LEVER:           LeverAdapter,
    ATSType.ASHBY:           AshbyAdapter,
    ATSType.SMARTRECRUITERS: SmartRecruitersAdapter,
    ATSType.WORKABLE:        WorkableAdapter,
    ATSType.RECRUITEE:       RecruiteeAdapter,
    ATSType.WORKDAY:         WorkdayAdapter,
}

__all__ = [
    "BaseAdapter",
    "GreenhouseAdapter",
    "LeverAdapter",
    "AshbyAdapter",
    "SmartRecruitersAdapter",
    "WorkableAdapter",
    "RecruiteeAdapter",
    "USAJobsAdapter",
    "AdzunaAdapter",
    "WorkdayAdapter",
    "EmailAlertsAdapter",
    "ATS_ADAPTER_MAP",
]
