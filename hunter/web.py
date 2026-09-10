from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from hunter import db
from hunter.apply import apply_in_browser, is_linkedin
from hunter.config import FRESH_HOURS, HOST, PORT
from hunter.pipeline import scan
from hunter.slack import notify_scan
from hunter.resume import tailor_for_job
from hunter.normalize import posted_age_hours, posted_label, utc_now

HTML = """<!doctype html>
<html>
<head>
  <meta charset="utf-8"/>
  <title>Analytics job hunter</title>
  <style>
    body { font-family: ui-sans-serif, system-ui, sans-serif; margin: 24px; background: #0f1419; color: #e7ecf3; }
    a { color: #8cb4ff; }
    table { border-collapse: collapse; width: 100%; }
    th, td { text-align: left; padding: 8px 10px; border-bottom: 1px solid #243042; vertical-align: top; }
    .ok { background: #1f6feb; color: white; border: 0; padding: 6px 10px; border-radius: 6px; cursor: pointer; }
    .no { background: #3d4450; color: white; border: 0; padding: 6px 10px; border-radius: 6px; cursor: pointer; }
    .go { background: #238636; color: white; border: 0; padding: 6px 10px; border-radius: 6px; cursor: pointer; }
    .meta { color: #9aa8b8; font-size: 13px; }
    form { display: inline; }
    .new { background: #238636; color: #fff; border-radius: 4px; padding: 1px 6px; font-size: 11px; margin-left: 6px; }
    th a { color: #e7ecf3; text-decoration: none; }
    th a:hover { color: #8cb4ff; text-decoration: underline; }
    th .arrow { color: #8cb4ff; margin-left: 4px; }
  </style>
</head>
<body>
  <h1>Analytics job hunter</h1>
  <p class="meta">Remote-eligible roles posted in the last 30 days, freshest first. Listed pay under $180k is dropped. Unknown pay stays in the queue for you to judge. Approve before any apply. LinkedIn Easy Apply is never automated.</p>
  <p class="meta">Public feeds + company ATS boards (Greenhouse/Lever/Ashby). LinkedIn and Indeed are not scraped — open these searches yourself:
    <a href="https://www.linkedin.com/jobs/search/?keywords=Senior%20Analytics%20Engineer&amp;f_WT=2" target="_blank" rel="noopener">LinkedIn Senior AE remote</a> ·
    <a href="https://www.linkedin.com/jobs/search/?keywords=Director%20Analytics%20Engineering&amp;f_WT=2" target="_blank" rel="noopener">LinkedIn Director AE</a> ·
    <a href="https://www.linkedin.com/jobs/search/?keywords=Manager%20Analytics%20Engineering&amp;f_WT=2" target="_blank" rel="noopener">LinkedIn Manager AE</a> ·
    <a href="https://www.indeed.com/jobs?q=Senior+Analytics+Engineer&amp;l=Remote&amp;fromage=3" target="_blank" rel="noopener">Indeed Senior AE remote</a> ·
    <a href="https://www.indeed.com/jobs?q=Director+Analytics+Engineering&amp;l=Remote&amp;fromage=3" target="_blank" rel="noopener">Indeed Director AE</a> ·
    <a href="https://www.indeed.com/jobs?q=Manager+Analytics+Engineering&amp;l=Remote&amp;fromage=3" target="_blank" rel="noopener">Indeed Manager AE</a>
  </p>
  <form method="post" action="/scan"><button class="ok" type="submit">Scan now</button></form>
  <p class="meta">Last scan: {{scan_stats}}</p>
  <table>
    <tr>{{headers}}<th>Action</th></tr>
    {{rows}}
  </table>
</body>
</html>
"""


def _row_html(job) -> str:
    pay = "not listed"
    if job["salary_min"] or job["salary_max"]:
        pay = f"${job['salary_min'] or '?'} – ${job['salary_max'] or '?'}"
    actions = []
    if job["status"] == "review":
        actions.append(f'<form method="post" action="/approve/{job["id"]}"><button class="ok">Approve & tailor</button></form>')
        actions.append(f'<form method="post" action="/reject/{job["id"]}"><button class="no">Skip</button></form>')
    if job["status"] == "approved":
        actions.append(f'<form method="post" action="/apply/{job["id"]}"><button class="go">Open & fill (you submit)</button></form>')
    resume = ""
    if job["tailored_resume_path"]:
        resume = f'<div class="meta">Resume: {job["tailored_resume_path"]}</div>'
    age = posted_age_hours(job["posted_at"])
    badge = '<span class="new">NEW</span>' if age is not None and age <= FRESH_HOURS else ""
    return f"""
    <tr>
      <td>{job['id']}</td>
      <td>
        <strong>{_esc(job['title'])}</strong><br/>
        {_esc(job['company'] or '')} · {_esc(job['source'])} · {_esc(job['location'] or '')}<br/>
        <a href="{_esc(job['url'])}" target="_blank" rel="noopener">listing</a>
        {resume}
        <div class="meta">{_esc((job['fit_notes'] or '')[:280])}</div>
      </td>
      <td>{job['fit_score'] or ''}</td>
      <td class="meta">{_esc(posted_label(job['posted_at']))}{badge}</td>
      <td>{_esc(pay)}<br/><span class="meta">{job['salary_status']}</span></td>
      <td>{job['status']}</td>
      <td>{' '.join(actions)}</td>
    </tr>
    """


COLUMNS = [
    ("id", "ID"),
    ("role", "Role"),
    ("fit", "Fit"),
    ("posted", "Posted"),
    ("pay", "Pay"),
    ("status", "Status"),
]

# Clicking a new column starts descending, since highest-fit and newest are the
# useful defaults. Clicking the active column flips direction.
def _headers_html(sort: str, descending: bool) -> str:
    cells = []
    for key, label in COLUMNS:
        active = key == sort
        next_desc = not descending if active else True
        arrow = f' <span class="arrow">{"▼" if descending else "▲"}</span>' if active else ""
        query = f"/?sort={key}&amp;dir={'desc' if next_desc else 'asc'}"
        cells.append(f'<th><a href="{query}">{label}</a>{arrow}</th>')
    return "".join(cells)


def _esc(value: str) -> str:
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


class Handler(BaseHTTPRequestHandler):
    last_scan = "{}"

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return

    def _html(self, sort: str, descending: bool) -> bytes:
        # Sorting happens in SQL so the visible page is the true top of the
        # whole queue, not just a reordering of an arbitrary first slice.
        # 'skipped' means a filter rejected it, not that you decided
        # anything, so it is noise on the review page.
        visible = db.list_jobs(
            limit=80,
            sort=sort,
            descending=descending,
            exclude_status=("stale", "skipped"),
        )
        rows = "".join(_row_html(job) for job in visible)
        page = HTML.replace("{{rows}}", rows or "<tr><td colspan=7>No roles yet. Scan now.</td></tr>")
        page = page.replace("{{headers}}", _headers_html(sort, descending))
        page = page.replace("{{scan_stats}}", Handler.last_scan)
        return page.encode()

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path != "/":
            self.send_error(404)
            return
        params = parse_qs(parsed.query)
        sort = (params.get("sort") or [db.DEFAULT_SORT])[0]
        if sort not in db.SORT_COLUMNS:
            sort = db.DEFAULT_SORT
        descending = (params.get("dir") or ["desc"])[0] != "asc"
        body = self._html(sort, descending)
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        try:
            if path == "/scan":
                stats = scan()
                jobs = stats.pop("jobs", [])
                Handler.last_scan = json.dumps(stats)
                try:
                    notify_scan(stats, jobs)
                except Exception as exc:
                    Handler.last_scan = json.dumps({"scan": stats, "slack_error": str(exc)})
            elif path.startswith("/approve/"):
                job_id = int(path.rsplit("/", 1)[-1])
                job = db.get_job(job_id)
                if job:
                    tailored = tailor_for_job(dict(job))
                    db.update_job(
                        job_id,
                        status="approved",
                        tailored_resume_path=tailored["tailored_resume_path"],
                        cover_note=tailored["cover_note"],
                        decided_at=utc_now(),
                    )
            elif path.startswith("/reject/"):
                job_id = int(path.rsplit("/", 1)[-1])
                db.update_job(job_id, status="rejected", decided_at=utc_now())
            elif path.startswith("/apply/"):
                job_id = int(path.rsplit("/", 1)[-1])
                job = db.get_job(job_id)
                if not job or job["status"] != "approved":
                    raise RuntimeError("Approve first")
                url = job["apply_url"] or job["url"]
                if is_linkedin(url):
                    Handler.last_scan = (
                        f"LinkedIn listing {job_id}: upload {job['tailored_resume_path']} yourself. {url}"
                    )
                else:
                    apply_in_browser(url, job["tailored_resume_path"], job["cover_note"] or "")
                    db.update_job(job_id, status="applied", applied_at=utc_now())
        except Exception as exc:
            Handler.last_scan = str(exc)
        self.send_response(303)
        # Return to the same sort order the action was taken from, so working
        # down a sorted list does not reset to the default on every approval.
        self.send_header("Location", self._return_path())
        self.end_headers()

    def _return_path(self) -> str:
        referer = urlparse(self.headers.get("Referer") or "")
        params = parse_qs(referer.query)
        sort = (params.get("sort") or [""])[0]
        if sort not in db.SORT_COLUMNS:
            return "/"
        direction = "asc" if (params.get("dir") or [""])[0] == "asc" else "desc"
        return f"/?sort={sort}&dir={direction}"


def serve() -> None:
    db.init_db()
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
