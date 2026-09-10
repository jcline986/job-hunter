from __future__ import annotations

import re

from hunter.config import (
    FRESH_HOURS,
    MAX_AGE_HOURS,
    MIN_COMP_USD,
    TITLE_PATTERNS,
    WIDE_TITLE_PATTERNS,
)
from hunter.normalize import (
    SCIENCE_NEGATIVE,
    TITLE_NEGATIVE,
    is_fresh,
    posted_age_hours,
    salary_status,
    us_eligible,
)

KEYWORD_WEIGHTS = {
    "analytics engineer": 8,
    "analytics engineering": 8,
    "dbt": 5,
    "snowflake": 4,
    "redshift": 4,
    "bigquery": 3,
    "looker": 3,
    "tableau": 3,
    "sql": 3,
    "python": 3,
    "airflow": 3,
    "spark": 2,
    "kafka": 2,
    "telemetry": 3,
    "dbt cloud": 4,
    "data modeling": 3,
    "dimensional modeling": 3,
    "leadership": 2,
    "manager": 2,
    "director": 2,
    "stakeholder": 2,
    "self-serve": 3,
    "self serve": 3,
    "ai": 1,
}

# Titles that match the wide net but are a different career track.
OFF_TRACK = re.compile(
    r"\b(people|hr|human resources|talent|compensation|marketing|sales|revenue|"
    r"clinical|credit risk|actuarial|audit|tax|treasury|quantitative|security|"
    r"supply chain|procurement|pricing)\b",
    re.IGNORECASE,
)


# "Analytics Engineer, GTM Data Science & Analytics" is an analytics engineering
# role whose team happens to be named Data Science. Match the role, not the org.
ROLE_IS_ANALYTICS_ENGINEER = re.compile(r"analytics\s+engineer", re.IGNORECASE)


def _is_excluded(title: str) -> bool:
    text = title or ""
    if TITLE_NEGATIVE.search(text):
        return True
    if SCIENCE_NEGATIVE.search(text):
        return not ROLE_IS_ANALYTICS_ENGINEER.search(text)
    return False


def title_is_target(title: str) -> bool:
    """Core analytics-engineering titles."""
    if _is_excluded(title):
        return False
    return any(re.search(p, title or "", re.IGNORECASE) for p in TITLE_PATTERNS)


def title_is_candidate(title: str) -> bool:
    """Wide net: any senior-or-above analytics/data role."""
    if _is_excluded(title):
        return False
    text = title or ""
    if title_is_target(text):
        return True
    return any(re.search(p, text, re.IGNORECASE) for p in WIDE_TITLE_PATTERNS)


def score_job(job: dict) -> tuple[float, str]:
    title = job.get("title") or ""
    description = (job.get("description") or "").lower()
    blob = f"{title.lower()} {description}"
    notes: list[str] = []
    score = 0.0

    if title_is_target(title):
        score += 30
        notes.append("core analytics engineering title")
    elif re.search(r"analytics engineer", title, re.IGNORECASE):
        score += 20
        notes.append("adjacent analytics engineer title")
    elif re.search(r"data engineer", title, re.IGNORECASE):
        score += 10
        notes.append("data engineering adjacent")
    else:
        notes.append("wide-net analytics/data title")

    if OFF_TRACK.search(title):
        score -= 12
        notes.append("different analytics track")

    for keyword, weight in KEYWORD_WEIGHTS.items():
        if keyword in blob:
            score += weight

    status = salary_status(MIN_COMP_USD, job.get("salary_min"), job.get("salary_max"))
    if status == "meets":
        score += 15
        notes.append("compensation at or above $180k")
    elif status == "below":
        score -= 20
        notes.append("listed pay below $180k")
    else:
        notes.append("compensation not listed")

    if job.get("remote_eligible"):
        score += 8
        notes.append("remote eligible")
    else:
        score -= 15
        notes.append("remote not clear")

    # Freshness ranks rather than eliminates: a three-week-old posting is still
    # open, it just should not outrank something published today.
    age = posted_age_hours(job.get("posted_at"))
    if age is None:
        notes.append("posted date unknown")
    elif age <= FRESH_HOURS:
        score += 12
        notes.append("posted in last 24h")
    elif age <= 72:
        score += 6
        notes.append(f"posted {max(1, int(age / 24))}d ago")
    else:
        days = int(age / 24)
        score -= min(10, days * 0.25)
        notes.append(f"posted {days}d ago")

    return round(score, 1), "; ".join(notes)


def should_keep(job: dict) -> bool:
    if not job.get("remote_eligible"):
        return False
    if not us_eligible(
        job.get("title") or "", job.get("location") or "", job.get("description") or ""
    ):
        return False
    if salary_status(MIN_COMP_USD, job.get("salary_min"), job.get("salary_max")) == "below":
        return False
    if not is_fresh(job.get("posted_at"), MAX_AGE_HOURS):
        return False
    return title_is_candidate(job.get("title") or "")
