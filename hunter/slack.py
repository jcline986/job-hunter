from __future__ import annotations

import json
import os
import ssl
from typing import Any, Iterable, Mapping, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import certifi

from hunter.config import HOST, PORT, ROOT, SLACK_BOT_TOKEN, SLACK_CHANNEL
from hunter.normalize import posted_label

SLACK_API = "https://slack.com/api/chat.postMessage"
_SSL = ssl.create_default_context(cafile=certifi.where())


def bot_token() -> str:
    return (SLACK_BOT_TOKEN or os.getenv("SLACK_BOT_TOKEN", "")).strip()


def channel() -> str:
    return (SLACK_CHANNEL or os.getenv("SLACK_CHANNEL", "")).strip()


def notify_empty() -> bool:
    raw = os.getenv("SLACK_NOTIFY_EMPTY", "1").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def configured() -> bool:
    return bool(bot_token() and channel())


def _job_line(job: Mapping[str, Any]) -> str:
    title = job.get("title") or "Untitled"
    company = job.get("company") or "Unknown company"
    url = job.get("apply_url") or job.get("url") or ""
    pay = "salary not posted"
    if job.get("salary_min") or job.get("salary_max"):
        lo = job.get("salary_min") or "?"
        hi = job.get("salary_max") or "?"
        pay = f"${lo}–${hi}"
    elif job.get("salary_status"):
        pay = str(job["salary_status"])
    link = f"<{url}|{title}>" if url else title
    age = posted_label(job.get("posted_at"))
    return f"• {link} — {company} ({pay}, {age})"


def format_scan_message(stats: Mapping[str, Any], jobs: Iterable[Mapping[str, Any]]) -> str:
    jobs = sorted(
        jobs, key=lambda j: float(j.get("fit_score") or 0), reverse=True
    )
    inserted = int(stats.get("inserted") or len(jobs) or 0)
    fetched = stats.get("fetched", "?")
    review = f"http://{HOST}:{PORT}"
    header = (
        f"*Analytics Job Hunter* scan finished\n"
        f"{inserted} new role(s) · {fetched} fetched · review locally at {review}"
    )
    dead = (stats.get("sources") or {}).get("dead_boards") or []
    if dead:
        header += f"\n:warning: {len(dead)} board(s) returned nothing: {', '.join(dead[:5])}"
    if not jobs:
        return header + "\nNo new matches this run."
    lines = [_job_line(job) for job in jobs[:15]]
    extra = f"\n…and {len(jobs) - 15} more" if len(jobs) > 15 else ""
    return header + "\n" + "\n".join(lines) + extra


def post_slack(text: str, token: Optional[str] = None, channel_id: Optional[str] = None) -> None:
    tok = (token or bot_token()).strip()
    dest = (channel_id or channel()).strip()
    if not tok or not dest:
        print("Slack skipped: set SLACK_BOT_TOKEN and SLACK_CHANNEL in .env")
        return
    payload = json.dumps(
        {
            "channel": dest,
            "text": text,
            "unfurl_links": False,
            "unfurl_media": False,
        }
    ).encode()
    req = Request(
        SLACK_API,
        data=payload,
        headers={
            "Authorization": f"Bearer {tok}",
            "Content-Type": "application/json; charset=utf-8",
        },
        method="POST",
    )
    try:
        with urlopen(req, timeout=20, context=_SSL) as resp:
            body = json.loads(resp.read().decode())
    except HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        raise RuntimeError(f"Slack HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"Slack request failed: {exc}") from exc
    if not body.get("ok"):
        raise RuntimeError(f"Slack API error: {body.get('error')}")


def notify_scan(stats: Mapping[str, Any], jobs: Iterable[Mapping[str, Any]] | None = None) -> None:
    if not configured():
        print("Slack skipped: set SLACK_BOT_TOKEN and SLACK_CHANNEL in .env")
        return
    job_list = list(jobs or stats.get("jobs") or [])
    inserted = int(stats.get("inserted") or 0)
    if inserted == 0 and not job_list and not notify_empty():
        return
    post_slack(format_scan_message(stats, job_list))


def notify_test() -> None:
    post_slack(
        "*Analytics Job Hunter* test ping from the Slack app.\n"
        f"Repo: `{ROOT.name}` · review UI: http://{HOST}:{PORT}"
    )
