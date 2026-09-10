from __future__ import annotations

import json
import logging
import re
from html import unescape  # noqa: F401

import httpx

from hunter.config import ADZUNA_APP_ID, ADZUNA_APP_KEY
from hunter.normalize import (
    dedupe_key,
    fingerprint,
    is_remote_eligible,
    parse_salary,
    utc_now,
)

log = logging.getLogger("hunter.sources")
HEADERS = {
    "User-Agent": "job-hunter/0.1 (personal job search)"
}


def _strip_html(text: str) -> str:
    text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", text or "")
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    return unescape(re.sub(r"\s+", " ", text)).strip()


def _base_job(**kwargs) -> dict:
    company = kwargs.get("company") or ""
    title = kwargs.get("title") or ""
    url = kwargs.get("url") or ""
    source = kwargs["source"]
    description = kwargs.get("description") or ""
    location = kwargs.get("location") or ""
    salary_min, salary_max, salary_raw = parse_salary(
        " ".join([kwargs.get("salary_raw") or "", description, title])
    )
    if kwargs.get("salary_min"):
        salary_min = kwargs["salary_min"]
    if kwargs.get("salary_max"):
        salary_max = kwargs["salary_max"]
    return {
        "fingerprint": fingerprint(source, url, title, company),
        "dedupe_key": dedupe_key(title, company) or None,
        "source": source,
        "title": title.strip(),
        "company": company.strip(),
        "location": location.strip(),
        "url": url,
        "apply_url": kwargs.get("apply_url") or url,
        "description": description[:20_000],
        "salary_min": salary_min,
        "salary_max": salary_max,
        "salary_raw": salary_raw or kwargs.get("salary_raw"),
        "remote_eligible": 1 if is_remote_eligible(title, location, description) else 0,
        "posted_at": kwargs.get("posted_at"),
        "first_seen_at": utc_now(),
    }


def fetch_indeed_rss() -> list[dict]:
    """Indeed retired the public RSS URL (404 as of 2026). Kept as a no-op hook."""
    log.info("Indeed RSS is unavailable; skipping.")
    return []


def fetch_remotive() -> list[dict]:
    jobs: list[dict] = []
    queries = [
        "analytics engineer",
        "analytics engineering",
        "senior data engineer",
        "director data engineering",
    ]
    try:
        with httpx.Client(timeout=30.0, headers=HEADERS, follow_redirects=True) as client:
            for query in queries:
                payload = client.get(
                    "https://remotive.com/api/remote-jobs",
                    params={"search": query},
                ).json()
                for item in payload.get("jobs", []):
                    jobs.append(
                        _base_job(
                            source="remotive",
                            title=item.get("title") or "",
                            company=(item.get("company_name") or ""),
                            location=item.get("candidate_required_location") or "Remote",
                            url=item.get("url") or item.get("job_url") or "",
                            description=_strip_html(item.get("description") or ""),
                            posted_at=item.get("publication_date"),
                            salary_raw=item.get("salary") or "",
                        )
                    )
    except Exception as exc:
        log.warning("Remotive fetch failed: %s", exc)
        return jobs
    return jobs


def fetch_remoteok() -> list[dict]:
    jobs: list[dict] = []
    url = "https://remoteok.com/api"
    try:
        with httpx.Client(timeout=30.0, headers=HEADERS, follow_redirects=True) as client:
            payload = client.get(url).json()
    except Exception as exc:
        log.warning("RemoteOK fetch failed: %s", exc)
        return jobs
    for item in payload:
        if not isinstance(item, dict) or not item.get("position"):
            continue
        blob = " ".join(
            [
                item.get("position") or "",
                item.get("description") or "",
                " ".join(item.get("tags") or []),
            ]
        ).lower()
        if "analytics" not in blob and "data engineer" not in blob:
            continue
        salary_min = item.get("salary_min") or None
        salary_max = item.get("salary_max") or None
        try:
            salary_min = int(salary_min) if salary_min else None
            salary_max = int(salary_max) if salary_max else None
        except (TypeError, ValueError):
            salary_min = salary_max = None
        jobs.append(
            _base_job(
                source="remoteok",
                title=item.get("position") or "",
                company=item.get("company") or "",
                location="Remote",
                url=item.get("url") or item.get("apply_url") or "",
                apply_url=item.get("apply_url") or item.get("url"),
                description=_strip_html(item.get("description") or ""),
                posted_at=item.get("date"),
                salary_min=salary_min,
                salary_max=salary_max,
            )
        )
    return jobs


def fetch_adzuna() -> list[dict]:
    if not ADZUNA_APP_ID or not ADZUNA_APP_KEY:
        return []
    jobs: list[dict] = []
    queries = ["senior analytics engineer", "analytics engineering manager", "director analytics engineering"]
    try:
        with httpx.Client(timeout=30.0, headers=HEADERS, follow_redirects=True) as client:
            for query in queries:
                url = "https://api.adzuna.com/v1/api/jobs/us/search/1"
                resp = client.get(
                    url,
                    params={
                        "app_id": ADZUNA_APP_ID,
                        "app_key": ADZUNA_APP_KEY,
                        "what": query,
                        "where": "remote",
                        "sort_by": "date",
                        "max_days_old": 7,
                        "results_per_page": 50,
                    },
                )
                resp.raise_for_status()
                for item in resp.json().get("results", []):
                    loc = (item.get("location") or {}).get("display_name") or "Remote"
                    jobs.append(
                        _base_job(
                            source="adzuna",
                            title=item.get("title") or "",
                            company=(item.get("company") or {}).get("display_name") or "",
                            location=loc,
                            url=item.get("redirect_url") or item.get("adref") or "",
                            description=_strip_html(item.get("description") or ""),
                            posted_at=item.get("created"),
                            salary_min=int(item["salary_min"]) if item.get("salary_min") else None,
                            salary_max=int(item["salary_max"]) if item.get("salary_max") else None,
                        )
                    )
    except Exception as exc:
        log.warning("Adzuna fetch failed: %s", exc)
    return jobs


def _url_key(url: str) -> str:
    return (url or "").split("?")[0].rstrip("/").lower()


def himalayas_location(item: dict) -> str:
    """Turn Himalayas locationRestrictions into the location string we filter on.

    An empty list means worldwide. The API has no `location` field; using
    "Remote" as a fallback hid badges like "Nigeria only".
    """
    names: list[str] = []
    seen: set[str] = set()
    for entry in item.get("locationRestrictions") or []:
        if isinstance(entry, str):
            name = entry.strip()
        elif isinstance(entry, dict):
            name = str(entry.get("name") or entry.get("slug") or entry.get("alpha2") or "").strip()
            name = name.replace("-", " ")
        else:
            name = ""
        key = name.lower()
        if name and key not in seen:
            seen.add(key)
            names.append(name)
    if not names:
        return "Remote"
    if len(names) == 1:
        return f"{names[0]} only"
    return ", ".join(names)


def himalayas_locations_for_urls(urls: list[str]) -> dict[str, str]:
    """Look up locationRestrictions for Himalayas URLs already in the queue."""
    by_slug: dict[str, list[str]] = {}
    for url in urls:
        match = re.search(r"himalayas\.app/companies/([^/]+)/", url or "", re.I)
        if match:
            by_slug.setdefault(match.group(1).lower(), []).append(url)
    found: dict[str, str] = {}
    if not by_slug:
        return found
    try:
        with httpx.Client(timeout=30.0, headers=HEADERS, follow_redirects=True) as client:
            for slug, slug_urls in by_slug.items():
                payload = client.get(
                    "https://himalayas.app/jobs/api/search",
                    params={"company": slug},
                ).json()
                items = payload.get("jobs") or []
                indexed: list[tuple[str, set[str]]] = []
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    keys = {
                        _url_key(item.get("applicationLink") or ""),
                        _url_key(item.get("guid") or ""),
                        _url_key(item.get("url") or ""),
                    }
                    keys.discard("")
                    indexed.append((himalayas_location(item), keys))
                for url in slug_urls:
                    key = _url_key(url)
                    path = url.rstrip("/").split("/")[-1].lower()
                    for location, keys in indexed:
                        if key in keys or any(path and path in candidate for candidate in keys):
                            found[key] = location
                            break
    except Exception as exc:
        log.warning("Himalayas location lookup failed: %s", exc)
    return found


def fetch_himalayas() -> list[dict]:
    jobs: list[dict] = []
    url = "https://himalayas.app/jobs/api?limit=100"
    try:
        with httpx.Client(timeout=30.0, headers=HEADERS, follow_redirects=True) as client:
            payload = client.get(url).json()
    except Exception as exc:
        log.warning("Himalayas fetch failed: %s", exc)
        return jobs
    items = payload if isinstance(payload, list) else payload.get("jobs") or payload.get("data") or []
    for item in items:
        if not isinstance(item, dict):
            continue
        title = item.get("title") or item.get("jobTitle") or ""
        description = _strip_html(json.dumps(item.get("description") or item.get("excerpt") or ""))
        jobs.append(
            _base_job(
                source="himalayas",
                title=title,
                company=(item.get("companyName") or (item.get("company") or {}).get("name") or ""),
                location=himalayas_location(item),
                url=item.get("applicationLink") or item.get("url") or item.get("guid") or "",
                description=description,
                posted_at=item.get("pubDate") or item.get("postedAt"),
            )
        )
    return jobs


def fetch_themuse() -> list[dict]:
    jobs: list[dict] = []
    categories = ["Data and Analytics", "Data Science"]
    try:
        with httpx.Client(timeout=30.0, headers=HEADERS, follow_redirects=True) as client:
            for category in categories:
                for page in range(0, 2):
                    resp = client.get(
                        "https://www.themuse.com/api/public/jobs",
                        params={
                            "page": page,
                            "descending": "true",
                            "category": category,
                            "location": "Flexible / Remote",
                            "level": "Senior Level",
                        },
                    )
                    if resp.status_code != 200:
                        break
                    payload = resp.json()
                    for item in payload.get("results", []):
                        locs = ", ".join(
                            loc.get("name", "") for loc in (item.get("locations") or []) if loc.get("name")
                        )
                        refs = item.get("refs") or {}
                        jobs.append(
                            _base_job(
                                source="themuse",
                                title=item.get("name") or "",
                                company=(item.get("company") or {}).get("name") or "",
                                location=locs or "Remote",
                                url=refs.get("landing_page") or "",
                                apply_url=refs.get("external_url") or refs.get("landing_page") or "",
                                description=_strip_html(item.get("contents") or ""),
                                posted_at=item.get("publication_date"),
                            )
                        )
                    if page + 1 >= payload.get("page_count", 0):
                        break
            for page in range(0, 2):
                resp = client.get(
                    "https://www.themuse.com/api/public/jobs",
                    params={
                        "page": page,
                        "descending": "true",
                        "category": "Data and Analytics",
                        "location": "Flexible / Remote",
                        "level": "Management",
                    },
                )
                if resp.status_code != 200:
                    break
                payload = resp.json()
                for item in payload.get("results", []):
                    locs = ", ".join(
                        loc.get("name", "") for loc in (item.get("locations") or []) if loc.get("name")
                    )
                    refs = item.get("refs") or {}
                    jobs.append(
                        _base_job(
                            source="themuse",
                            title=item.get("name") or "",
                            company=(item.get("company") or {}).get("name") or "",
                            location=locs or "Remote",
                            url=refs.get("landing_page") or "",
                            apply_url=refs.get("external_url") or refs.get("landing_page") or "",
                            description=_strip_html(item.get("contents") or ""),
                            posted_at=item.get("publication_date"),
                        )
                    )
    except Exception as exc:
        log.warning("The Muse fetch failed: %s", exc)
    return jobs


def fetch_jobicy() -> list[dict]:
    jobs: list[dict] = []
    try:
        with httpx.Client(timeout=30.0, headers=HEADERS, follow_redirects=True) as client:
            for tag in ("data", "engineering"):
                payload = client.get(
                    "https://jobicy.com/api/v2/remote-jobs",
                    params={"count": 100, "tag": tag},
                ).json()
                for item in payload.get("jobs") or []:
                    jobs.append(
                        _base_job(
                            source="jobicy",
                            title=item.get("jobTitle") or "",
                            company=item.get("companyName") or "",
                            location=item.get("jobGeo") or "Remote",
                            url=item.get("url") or "",
                            description=_strip_html(
                                item.get("jobDescription") or item.get("jobExcerpt") or ""
                            ),
                            posted_at=item.get("pubDate"),
                            salary_raw=str(item.get("annualSalaryMin") or "")
                            + "-"
                            + str(item.get("annualSalaryMax") or ""),
                            salary_min=int(item["annualSalaryMin"]) if item.get("annualSalaryMin") else None,
                            salary_max=int(item["annualSalaryMax"]) if item.get("annualSalaryMax") else None,
                        )
                    )
    except Exception as exc:
        log.warning("Jobicy fetch failed: %s", exc)
        return jobs
    return jobs


def fetch_arbeitnow() -> list[dict]:
    jobs: list[dict] = []
    try:
        with httpx.Client(timeout=30.0, headers=HEADERS, follow_redirects=True) as client:
            payload = client.get("https://www.arbeitnow.com/api/job-board-api").json()
    except Exception as exc:
        log.warning("Arbeitnow fetch failed: %s", exc)
        return jobs
    for item in payload.get("data") or []:
        jobs.append(
            _base_job(
                source="arbeitnow",
                title=item.get("title") or "",
                company=item.get("company_name") or "",
                location=item.get("location") or "Remote",
                url=item.get("url") or "",
                description=_strip_html(item.get("description") or ""),
                posted_at=str(item.get("created_at") or ""),
            )
        )
    return jobs


def fetch_weworkremotely() -> list[dict]:
    import feedparser

    jobs: list[dict] = []
    feeds = [
        "https://weworkremotely.com/categories/remote-programming-jobs.rss",
        "https://weworkremotely.com/categories/remote-data-jobs.rss",
    ]
    for url in feeds:
        parsed = feedparser.parse(url, request_headers=HEADERS)
        for entry in parsed.entries:
            title = entry.get("title", "")
            company = ""
            if ":" in title:
                company, title = title.split(":", 1)
            jobs.append(
                _base_job(
                    source="weworkremotely",
                    title=title.strip(),
                    company=company.strip(),
                    location="Remote",
                    url=entry.get("link", ""),
                    description=_strip_html(entry.get("summary", "") or entry.get("description", "")),
                    posted_at=entry.get("published"),
                )
            )
    return jobs


def ingest_listing(url: str, title: str = "", company: str = "", description: str = "") -> dict:
    if not title:
        try:
            with httpx.Client(timeout=20.0, headers=HEADERS, follow_redirects=True) as client:
                html = client.get(url).text
            og = re.search(r'property="og:title"\s+content="([^"]+)"', html, re.I)
            t = re.search(r"<title>(.*?)</title>", html, re.I | re.S)
            title = _strip_html((og.group(1) if og else "") or (t.group(1) if t else "") or url)
        except Exception:
            title = url
    return _base_job(
        source="manual",
        title=title,
        company=company,
        location="Remote",
        url=url,
        description=description or title,
    )


def fetch_all() -> tuple[list[dict], dict[str, int]]:
    collected: list[dict] = []
    source_counts: dict[str, int] = {}
    fetchers = (
        fetch_indeed_rss,
        fetch_remotive,
        fetch_remoteok,
        fetch_adzuna,
        fetch_himalayas,
        fetch_themuse,
        fetch_jobicy,
        fetch_weworkremotely,
        fetch_arbeitnow,
    )
    for fetcher in fetchers:
        try:
            batch = fetcher()
            source_counts[fetcher.__name__.replace("fetch_", "")] = len(batch)
            log.info("%s returned %s jobs", fetcher.__name__, len(batch))
            collected.extend(batch)
        except Exception as exc:
            source_counts[fetcher.__name__.replace("fetch_", "")] = 0
            log.warning("%s failed: %s", fetcher.__name__, exc)
    try:
        from hunter.ats import fetch_ats

        ats_jobs, health = fetch_ats()
        source_counts["ats"] = len(ats_jobs)
        source_counts.update(health)
        collected.extend(ats_jobs)
    except Exception as exc:
        source_counts["ats"] = 0
        log.warning("ATS fetch failed: %s", exc)
    return collected, source_counts
