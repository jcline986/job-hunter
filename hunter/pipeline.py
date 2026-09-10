from __future__ import annotations

from hunter import db
from hunter.config import MAX_AGE_DAYS, MAX_AGE_HOURS, MIN_COMP_USD
from hunter.fit import score_job, should_keep
from hunter.normalize import is_fresh, salary_status, utc_now, us_eligible
from hunter.sources import _url_key, fetch_all, himalayas_locations_for_urls, ingest_listing


def _prepare(job: dict) -> dict:
    fit_score, fit_notes = score_job(job)
    job["fit_score"] = fit_score
    job["fit_notes"] = fit_notes
    job["salary_status"] = salary_status(MIN_COMP_USD, job.get("salary_min"), job.get("salary_max"))
    job["status"] = "review"
    return job


def expire_stale_reviews() -> int:
    """Retire postings past the age window so the queue stays actionable."""
    expired = 0
    for job in db.list_jobs(status="review", limit=1000):
        if is_fresh(job["posted_at"], MAX_AGE_HOURS):
            continue
        db.update_job(job["id"], status="stale", decided_at=utc_now())
        expired += 1
    return expired


def drop_ineligible_reviews(fetched: list[dict] | None = None) -> int:
    """Remove queued roles that are not open to US applicants.

    Himalayas stores country locks in locationRestrictions, which older rows
    recorded as 'Remote'. Re-read those from the live feed (and a company
    lookup for anything not in this scan) before deciding.
    """
    locations = {}
    for job in fetched or []:
        for raw in (job.get("url"), job.get("apply_url")):
            key = _url_key(raw or "")
            if key and job.get("location"):
                locations[key] = job["location"]
    reviews = db.list_jobs(status="review", limit=2000)
    missing = [
        job["url"]
        for job in reviews
        if job["source"] == "himalayas" and _url_key(job["url"] or "") not in locations
    ]
    if missing:
        locations.update(himalayas_locations_for_urls(missing))
    dropped = 0
    for job in reviews:
        location = job["location"] or ""
        key = _url_key(job["url"] or "")
        fresh = locations.get(key)
        if fresh and fresh != location:
            db.update_job(job["id"], location=fresh)
            location = fresh
        if us_eligible(job["title"] or "", location, job["description"] or ""):
            continue
        db.update_job(job["id"], status="skipped", decided_at=utc_now())
        dropped += 1
    return dropped


def scan() -> dict:
    expired = expire_stale_reviews()
    fetched, source_counts = fetch_all()
    ineligible = drop_ineligible_reviews(fetched)

    inserted = 0
    skipped = 0
    duplicates = 0
    new_jobs = []
    seen_keys: set[str] = set()

    # Best-scoring copy of a role wins when several boards carry it.
    candidates = [job for job in fetched if should_keep(job)]
    skipped = len(fetched) - len(candidates)
    prepared = sorted(
        (_prepare(job) for job in candidates),
        key=lambda j: j["fit_score"],
        reverse=True,
    )

    for job in prepared:
        key = job.get("dedupe_key")
        if key and key in seen_keys:
            duplicates += 1
            continue
        if key:
            seen_keys.add(key)
        if db.upsert_job(job) == "inserted":
            inserted += 1
            new_jobs.append(job)
        else:
            duplicates += 1

    return {
        "fetched": len(fetched),
        "inserted": inserted,
        "duplicates": duplicates,
        "skipped": skipped,
        "expired_stale": expired,
        "dropped_ineligible": ineligible,
        "window_days": MAX_AGE_DAYS,
        "sources": source_counts,
        "jobs": new_jobs,
    }


def add_listing(url: str, title: str = "", company: str = "", description: str = "") -> dict:
    job = ingest_listing(url, title=title, company=company, description=description)
    result = db.upsert_job(_prepare(job))
    return {"result": result, "title": job["title"], "url": job["url"]}
