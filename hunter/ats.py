from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

import httpx

from hunter.boards import (
    ASHBY_BOARDS,
    GREENHOUSE_BOARDS,
    LEVER_COMPANIES,
    WORKDAY_QUERIES,
    WORKDAY_TENANTS,
)
from hunter.fit import title_is_candidate
from hunter.sources import HEADERS, _base_job, _strip_html

log = logging.getLogger("hunter.ats")

TIMEOUT = httpx.Timeout(20.0, connect=10.0)
WORKERS = 12


class BoardHealth:
    """Tracks which boards returned postings so dead slugs surface in the scan."""

    def __init__(self) -> None:
        self.live: dict[str, int] = {}
        self.dead: list[str] = []

    def record(self, key: str, count: int | None) -> None:
        if count is None:
            self.dead.append(key)
        else:
            self.live[key] = count

    def summary(self) -> dict:
        return {"live_boards": len(self.live), "dead_boards": sorted(self.dead)}


def _client() -> httpx.Client:
    return httpx.Client(timeout=TIMEOUT, headers=HEADERS, follow_redirects=True)


def _parallel(items: list, worker: Callable) -> list[dict]:
    jobs: list[dict] = []
    with ThreadPoolExecutor(WORKERS) as pool:
        for batch in pool.map(worker, items):
            jobs.extend(batch)
    return jobs


def _greenhouse_board(board: str, health: BoardHealth) -> list[dict]:
    jobs: list[dict] = []
    # content=true returns the full posting body, which is where pay-transparency
    # ranges and remote-eligibility language live.
    url = f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs"
    try:
        with _client() as client:
            resp = client.get(url, params={"content": "true"})
        if resp.status_code != 200:
            health.record(f"greenhouse:{board}", None)
            return jobs
        payload = resp.json()
    except Exception as exc:
        log.warning("Greenhouse %s failed: %s", board, exc)
        health.record(f"greenhouse:{board}", None)
        return jobs

    listings = payload.get("jobs") or []
    health.record(f"greenhouse:{board}", len(listings))
    for item in listings:
        title = item.get("title") or ""
        if not title_is_candidate(title):
            continue
        location = (item.get("location") or {}).get("name") or ""
        description = _strip_html(item.get("content") or "")
        offices = ", ".join(
            o.get("name", "") for o in (item.get("offices") or []) if o.get("name")
        )
        jobs.append(
            _base_job(
                source="greenhouse",
                title=title,
                company=board,
                location=location or offices or "",
                url=item.get("absolute_url") or "",
                description=description,
                posted_at=item.get("updated_at") or item.get("created_at"),
            )
        )
    return jobs


def _lever_company(company: str, health: BoardHealth) -> list[dict]:
    jobs: list[dict] = []
    try:
        with _client() as client:
            resp = client.get(
                f"https://api.lever.co/v0/postings/{company}", params={"mode": "json"}
            )
        if resp.status_code != 200:
            health.record(f"lever:{company}", None)
            return jobs
        payload = resp.json()
    except Exception as exc:
        log.warning("Lever %s failed: %s", company, exc)
        health.record(f"lever:{company}", None)
        return jobs

    if not isinstance(payload, list):
        health.record(f"lever:{company}", None)
        return jobs

    health.record(f"lever:{company}", len(payload))
    for item in payload:
        title = item.get("text") or ""
        if not title_is_candidate(title):
            continue
        categories = item.get("categories") or {}
        jobs.append(
            _base_job(
                source="lever",
                title=title,
                company=company,
                location=str(categories.get("location") or ""),
                url=item.get("hostedUrl") or item.get("applyUrl") or "",
                apply_url=item.get("applyUrl") or item.get("hostedUrl") or "",
                description=_strip_html(
                    item.get("descriptionPlain") or item.get("description") or title
                ),
                posted_at=item.get("createdAt"),
            )
        )
    return jobs


def _ashby_board(board: str, health: BoardHealth) -> list[dict]:
    jobs: list[dict] = []
    try:
        with _client() as client:
            resp = client.get(
                f"https://api.ashbyhq.com/posting-api/job-board/{board}",
                params={"includeCompensation": "true"},
            )
        if resp.status_code != 200:
            health.record(f"ashby:{board}", None)
            return jobs
        payload = resp.json()
    except Exception as exc:
        log.warning("Ashby %s failed: %s", board, exc)
        health.record(f"ashby:{board}", None)
        return jobs

    listings = payload.get("jobs") or []
    health.record(f"ashby:{board}", len(listings))
    for item in listings:
        title = item.get("title") or ""
        if not title_is_candidate(title):
            continue
        location = item.get("location") or ""
        if isinstance(location, dict):
            location = location.get("name") or ""
        comp = item.get("compensation") or {}
        summary = comp.get("compensationTierSummary") or comp.get("summaryComponents") or ""
        description = _strip_html(
            item.get("descriptionHtml") or item.get("descriptionPlain") or title
        )
        if item.get("isRemote"):
            location = f"{location} Remote".strip()
        jobs.append(
            _base_job(
                source="ashby",
                title=title,
                company=board,
                location=str(location),
                url=item.get("jobUrl") or item.get("applyUrl") or "",
                apply_url=item.get("applyUrl") or item.get("jobUrl") or "",
                description=description,
                posted_at=item.get("publishedAt") or item.get("updatedAt"),
                salary_raw=str(summary) if summary else None,
            )
        )
    return jobs


def _workday_tenant(entry: tuple[str, str, str], health: BoardHealth) -> list[dict]:
    tenant, subdomain, site = entry
    base = f"https://{tenant}.{subdomain}.myworkdayjobs.com"
    api = f"{base}/wday/cxs/{tenant}/{site}/jobs"
    jobs: list[dict] = []
    seen: set[str] = set()
    total_seen = 0
    ok = False

    try:
        with _client() as client:
            for query in WORKDAY_QUERIES:
                for offset in (0, 20):
                    resp = client.post(
                        api,
                        json={
                            "appliedFacets": {},
                            "limit": 20,
                            "offset": offset,
                            "searchText": query,
                        },
                    )
                    if resp.status_code != 200:
                        break
                    ok = True
                    postings = resp.json().get("jobPostings") or []
                    total_seen += len(postings)
                    for item in postings:
                        title = item.get("title") or ""
                        path = item.get("externalPath") or ""
                        if not path or path in seen:
                            continue
                        seen.add(path)
                        if not title_is_candidate(title):
                            continue
                        jobs.append(
                            _base_job(
                                source="workday",
                                title=title,
                                company=tenant,
                                location=item.get("locationsText") or "",
                                url=f"{base}/{site}{path}",
                                description=" ".join(
                                    filter(
                                        None,
                                        [
                                            title,
                                            item.get("locationsText") or "",
                                            item.get("bulletFields")
                                            and " ".join(item["bulletFields"])
                                            or "",
                                        ],
                                    )
                                ),
                                posted_at=item.get("postedOn"),
                            )
                        )
                    if len(postings) < 20:
                        break
    except Exception as exc:
        log.warning("Workday %s failed: %s", tenant, exc)

    health.record(f"workday:{tenant}", total_seen if ok else None)
    return jobs


def fetch_ats() -> tuple[list[dict], dict]:
    health = BoardHealth()
    jobs: list[dict] = []
    jobs.extend(_parallel(GREENHOUSE_BOARDS, lambda b: _greenhouse_board(b, health)))
    jobs.extend(_parallel(LEVER_COMPANIES, lambda c: _lever_company(c, health)))
    jobs.extend(_parallel(ASHBY_BOARDS, lambda b: _ashby_board(b, health)))
    jobs.extend(_parallel(WORKDAY_TENANTS, lambda t: _workday_tenant(t, health)))
    return jobs, health.summary()
