from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone

from rich.console import Console
from rich.table import Table

from hunter import db
from hunter.apply import apply_in_browser, is_linkedin
from hunter.config import HOST, PORT
from hunter.pipeline import add_listing, scan as run_scan
from hunter.resume import tailor_for_job
from hunter.slack import notify_scan, notify_test

console = Console()


def _print_jobs(rows) -> None:
    table = Table(show_lines=False)
    for col in ("id", "status", "score", "pay", "title", "company", "source"):
        table.add_column(col)
    for row in rows:
        pay = "unknown"
        if row["salary_min"] or row["salary_max"]:
            pay = f"{row['salary_min'] or '?'}-{row['salary_max'] or '?'}"
        table.add_row(
            str(row["id"]),
            row["status"],
            str(row["fit_score"] or ""),
            pay,
            (row["title"] or "")[:48],
            (row["company"] or "")[:24],
            row["source"],
        )
    console.print(table)


def cmd_scan(_: argparse.Namespace) -> int:
    db.init_db()
    stats = run_scan()
    jobs = stats.pop("jobs", [])
    console.print(stats)
    rows = db.list_jobs(status="review", limit=30)
    if rows:
        _print_jobs(rows)
    try:
        notify_scan(stats, jobs)
    except Exception as exc:
        console.print(f"Slack notify failed: {exc}")
    return 0


def cmd_preview(args: argparse.Namespace) -> int:
    """Show what tailoring would produce without writing a document."""
    from hunter.resume import build_tailoring, summary_problems

    job = db.get_job(args.job_id)
    if not job:
        console.print(f"No job {args.job_id}.")
        return 1
    result = build_tailoring(dict(job))
    console.print(f"[bold]{job['title']}[/bold] — {job['company']}")
    console.print(f"scope: {result['scope']} · source: {result['source']}")
    console.print(f"leading with: {', '.join(result['emphasis']) or 'general'}\n")
    console.print("[bold]Summary[/bold]")
    console.print(result["summary"] + "\n")
    console.print("[bold]Cover note[/bold]")
    console.print(result["cover_note"] + "\n")
    console.print(f"shared tooling: {', '.join(result['keywords']) or 'none'}")
    if result["gaps"]:
        console.print(
            f"[yellow]asked for but not on your resume: {', '.join(result['gaps'])}[/yellow]"
        )
    problems = summary_problems(result["summary"], job["title"] or "", job["description"] or "")
    console.print(f"checks: {'; '.join(problems) if problems else 'passed'}")
    return 0


def cmd_boards(_: argparse.Namespace) -> int:
    from hunter.ats import fetch_ats

    jobs, health = fetch_ats()
    console.print(
        f"{health['live_boards']} live boards returned {len(jobs)} candidate roles."
    )
    dead = health["dead_boards"]
    if dead:
        console.print(f"{len(dead)} board(s) returned nothing:")
        for name in dead:
            console.print(f"  {name}")
    return 0


def cmd_slack_test(_: argparse.Namespace) -> int:
    from hunter.slack import configured

    if not configured():
        console.print("Set SLACK_BOT_TOKEN and SLACK_CHANNEL in .env first.")
        return 1
    try:
        notify_test()
    except Exception as exc:
        console.print(f"Slack test failed: {exc}")
        return 1
    console.print("Sent Slack test message.")
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    db.init_db()
    _print_jobs(db.list_jobs(status=args.status, limit=args.limit))
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    job = db.get_job(args.id)
    if not job:
        console.print(f"No job {args.id}")
        return 1
    console.print_json(json.dumps(dict(job), default=str))
    return 0


def cmd_approve(args: argparse.Namespace) -> int:
    job = db.get_job(args.id)
    if not job:
        console.print(f"No job {args.id}")
        return 1
    tailored = tailor_for_job(dict(job))
    db.update_job(
        args.id,
        status="approved",
        tailored_resume_path=tailored["tailored_resume_path"],
        cover_note=tailored["cover_note"],
        decided_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    console.print(f"Approved. Resume: {tailored['tailored_resume_path']}")
    console.print(tailored["cover_note"])
    return 0


def cmd_reject(args: argparse.Namespace) -> int:
    db.update_job(
        args.id,
        status="rejected",
        decided_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    console.print(f"Rejected {args.id}")
    return 0


def cmd_apply(args: argparse.Namespace) -> int:
    job = db.get_job(args.id)
    if not job:
        console.print(f"No job {args.id}")
        return 1
    if job["status"] != "approved":
        console.print("Approve the role first so a tailored resume exists.")
        return 1
    url = job["apply_url"] or job["url"]
    if is_linkedin(url):
        console.print(
            "This listing is on LinkedIn. I will not auto-fill Easy Apply. "
            f"Upload this resume yourself:\n{job['tailored_resume_path']}\n{url}"
        )
        return 2
    console.print("Browser will open, fill what it can, then pause. You click Submit.")
    try:
        apply_in_browser(url, job["tailored_resume_path"], job["cover_note"] or "")
    except Exception as exc:
        console.print(str(exc))
        return 1
    db.update_job(
        args.id,
        status="applied",
        applied_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    console.print("Marked applied. Change status if you did not submit.")
    return 0


def cmd_add(args: argparse.Namespace) -> int:
    db.init_db()
    result = add_listing(args.url, title=args.title, company=args.company)
    console.print(result)
    return 0


def cmd_serve(_: argparse.Namespace) -> int:
    from hunter.web import serve

    console.print(f"Review queue: http://{HOST}:{PORT}")
    serve()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Find, tailor, and apply to analytics engineering roles.")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("scan").set_defaults(func=cmd_scan)
    listing = sub.add_parser("list")
    listing.add_argument("--status", default=None)
    listing.add_argument("--limit", type=int, default=50)
    listing.set_defaults(func=cmd_list)
    show = sub.add_parser("show")
    show.add_argument("id", type=int)
    show.set_defaults(func=cmd_show)
    approve = sub.add_parser("approve")
    approve.add_argument("id", type=int)
    approve.set_defaults(func=cmd_approve)
    reject = sub.add_parser("reject")
    reject.add_argument("id", type=int)
    reject.set_defaults(func=cmd_reject)
    apply_cmd = sub.add_parser("apply")
    apply_cmd.add_argument("id", type=int)
    apply_cmd.set_defaults(func=cmd_apply)
    add = sub.add_parser("add", help="Manually queue a listing URL (LinkedIn/Indeed/ATS).")
    add.add_argument("url")
    add.add_argument("--title", default="")
    add.add_argument("--company", default="")
    add.set_defaults(func=cmd_add)
    sub.add_parser("serve").set_defaults(func=cmd_serve)
    preview = sub.add_parser("preview", help="Show the tailored summary for a job without writing it.")
    preview.add_argument("job_id", type=int)
    preview.set_defaults(func=cmd_preview)
    sub.add_parser("boards", help="Probe every ATS board and report dead slugs.").set_defaults(func=cmd_boards)
    sub.add_parser("slack-test").set_defaults(func=cmd_slack_test)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
