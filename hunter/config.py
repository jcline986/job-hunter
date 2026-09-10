from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env", override=True)

PROFILE_DIR = ROOT / "profile"
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "hunter.db"
MASTER_RESUME_MD = PROFILE_DIR / "master_resume.md"
MASTER_RESUME_DOCX = PROFILE_DIR / "resume_template.docx"
TAILORED_DIR = PROFILE_DIR / "tailored"
CONTACT_PATH = PROFILE_DIR / "contact.json"

MIN_COMP_USD = 180_000

# Postings older than this leave the queue. Freshness also drives ranking, so a
# role posted today outranks one from three weeks ago without hiding the latter.
MAX_AGE_DAYS = int(os.getenv("HUNTER_MAX_AGE_DAYS", "30"))
MAX_AGE_HOURS = MAX_AGE_DAYS * 24
FRESH_HOURS = 24

TARGET_TITLES = [
    "Senior Analytics Engineer",
    "Director, Analytics Engineering",
    "Director of Analytics Engineering",
    "Director Analytics Engineering",
    "Manager, Analytics Engineering",
    "Manager of Analytics Engineering",
    "Analytics Engineering Manager",
    "Head of Analytics Engineering",
]

# Core analytics-engineering titles. These score highest.
TITLE_PATTERNS = [
    r"analytics\s+engineer",
    r"analytics\s+engineering",
    r"director[, ]+data\s+engineering",
    r"director\s+of\s+data\s+engineering",
    r"head\s+of\s+data\s+engineering",
    r"manager[, ]+data\s+engineering",
    r"manager\s+of\s+data\s+engineering",
    r"data\s+engineering\s+manager",
]

SENIORITY = r"(senior|sr\.?|staff|principal|lead|manager|director|head|vp|vice\s+president|chief)"

# Wide net: any senior-or-above analytics/data role. You filter the rest.
WIDE_TITLE_PATTERNS = [
    rf"{SENIORITY}\b.{{0,45}}\b(analytics|analytic|data|business\s+intelligence|\bbi\b)",
    rf"\b(analytics|data|business\s+intelligence)\b.{{0,45}}\b{SENIORITY}",
    r"\b(head|director|vp|vice\s+president)\b.{0,45}\b(insights|reporting)",
]

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini").strip()
ADZUNA_APP_ID = os.getenv("ADZUNA_APP_ID", "").strip()
ADZUNA_APP_KEY = os.getenv("ADZUNA_APP_KEY", "").strip()
SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN", "").strip()
SLACK_CHANNEL = os.getenv("SLACK_CHANNEL", "").strip()
HOST = os.getenv("HUNTER_HOST", "127.0.0.1")
PORT = int(os.getenv("HUNTER_PORT", "8765"))
