from __future__ import annotations

import sqlite3
from contextlib import contextmanager

from hunter.config import DATA_DIR, DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fingerprint TEXT NOT NULL UNIQUE,
    source TEXT NOT NULL,
    title TEXT NOT NULL,
    company TEXT,
    location TEXT,
    url TEXT NOT NULL,
    apply_url TEXT,
    description TEXT,
    salary_min INTEGER,
    salary_max INTEGER,
    salary_raw TEXT,
    remote_eligible INTEGER NOT NULL DEFAULT 1,
    posted_at TEXT,
    first_seen_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'new',
    fit_score REAL,
    fit_notes TEXT,
    salary_status TEXT NOT NULL DEFAULT 'unknown',
    tailored_resume_path TEXT,
    cover_note TEXT,
    decided_at TEXT,
    applied_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_first_seen ON jobs(first_seen_at);
"""


def init_db() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.executescript(SCHEMA)
        columns = {row[1] for row in conn.execute("PRAGMA table_info(jobs)")}
        if "dedupe_key" not in columns:
            conn.execute("ALTER TABLE jobs ADD COLUMN dedupe_key TEXT")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_jobs_dedupe ON jobs(dedupe_key)"
            )
        conn.commit()
    finally:
        conn.close()


@contextmanager
def connect():
    init_db()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def upsert_job(job: dict) -> str:
    """Insert a newly seen job. Returns 'inserted' or 'duplicate'.

    Deduplication happens on two levels: the exact source fingerprint, and a
    normalized company+title key so the same role surfaced by an aggregator and
    the company's own board only appears once.
    """
    with connect() as conn:
        existing = conn.execute(
            "SELECT id FROM jobs WHERE fingerprint = ? OR (dedupe_key IS NOT NULL AND dedupe_key = ?)",
            (job["fingerprint"], job.get("dedupe_key")),
        ).fetchone()
        if existing:
            return "duplicate"
        conn.execute(
            """
            INSERT INTO jobs (
                fingerprint, dedupe_key, source, title, company, location, url, apply_url,
                description, salary_min, salary_max, salary_raw, remote_eligible,
                posted_at, first_seen_at, status, fit_score, fit_notes, salary_status
            ) VALUES (
                :fingerprint, :dedupe_key, :source, :title, :company, :location, :url, :apply_url,
                :description, :salary_min, :salary_max, :salary_raw, :remote_eligible,
                :posted_at, :first_seen_at, :status, :fit_score, :fit_notes, :salary_status
            )
            """,
            job,
        )
        return "inserted"


# Sortable columns, mapped to (expression, null-guard). Keys are a whitelist:
# nothing from the query string ever reaches the SQL directly.
SORT_COLUMNS: dict[str, tuple[str, str | None]] = {
    "id": ("id", None),
    "role": ("title COLLATE NOCASE", None),
    "fit": ("fit_score", "fit_score IS NULL"),
    # posted_at holds mixed source formats, so NULLs sort last rather than
    # masquerading as recent.
    "posted": ("posted_at", "posted_at IS NULL"),
    "pay": ("salary_max", "salary_max IS NULL"),
    "status": ("status", None),
}
DEFAULT_SORT = "posted"


def _order_clause(sort: str, descending: bool) -> str:
    expression, null_guard = SORT_COLUMNS.get(sort) or SORT_COLUMNS[DEFAULT_SORT]
    direction = "DESC" if descending else "ASC"
    parts = []
    if null_guard:
        # Always ascending, so unknown values stay at the bottom either way.
        parts.append(null_guard)
    parts.append(f"{expression} {direction}")
    if sort != "fit":
        parts.append("fit_score DESC")
    return "ORDER BY " + ", ".join(parts)


def list_jobs(
    status: str | None = None,
    limit: int = 100,
    sort: str = DEFAULT_SORT,
    descending: bool = True,
    exclude_status: tuple[str, ...] = (),
) -> list[sqlite3.Row]:
    order = _order_clause(sort, descending)
    where: list[str] = []
    params: list = []
    if status:
        where.append("status = ?")
        params.append(status)
    if exclude_status:
        placeholders = ", ".join("?" for _ in exclude_status)
        where.append(f"status NOT IN ({placeholders})")
        params.extend(exclude_status)
    clause = f"WHERE {' AND '.join(where)}" if where else ""
    params.append(limit)
    with connect() as conn:
        rows = conn.execute(
            f"SELECT * FROM jobs {clause} {order} LIMIT ?", params
        ).fetchall()
        return list(rows)


def get_job(job_id: int) -> sqlite3.Row | None:
    with connect() as conn:
        return conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()


def update_job(job_id: int, **fields) -> None:
    if not fields:
        return
    assignments = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [job_id]
    with connect() as conn:
        conn.execute(f"UPDATE jobs SET {assignments} WHERE id = ?", values)
