# Job hunter

A local assistant that finds **remote-eligible** analytics/data roles, prefers **$180k+** when pay is posted, tailors a resume per listing, and **never applies until you approve**.

The profile in this repo is a **fictional sample**. Replace it with yours before you scan for real.

## What it does

1. **Scan** public aggregators (Remotive, RemoteOK, Himalayas, The Muse, Jobicy, We Work Remotely, Arbeitnow; Adzuna if you set keys) plus Greenhouse/Lever/Ashby ATS boards.
2. **Filter** to remote (or US-remote wording), roles a US applicant can take (country-only locks like “Nigeria only” are dropped), and compensation ≥ $180k when salary is posted. Unposted salaries stay in the queue for you to judge.
3. **Tailor** `profile/master_resume.md` into a per-job `.docx` plus a short cover note. Tailoring only leads with work already on the master resume — it will not invent tools.
4. **Queue** everything locally. You approve in the review UI or CLI.
5. **Apply assist** opens a visible browser, fills name/email/phone/LinkedIn and attaches the tailored resume when there is a file input, then **waits for you to submit**.

It does **not** scrape LinkedIn or automate Easy Apply (that violates LinkedIn’s terms). LinkedIn URLs are opened for you to apply yourself.

## Setup

```bash
git clone https://github.com/<you>/job-hunter.git
cd job-hunter
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python3 -m playwright install chromium
cp .env.example .env
```

Then replace the sample profile:

1. `profile/contact.json` — name, phone, email, LinkedIn
2. `profile/master_resume.md` — your resume
3. `profile/resume_template.docx` — optional Word template (tailoring clones this file’s styling)
4. `hunter/evidence.py` — `CAPABILITIES` evidence strings must stay true of your resume
5. `hunter/resume.py` — `IDENTITY` opening lines, same rule
6. `hunter/config.py` — title patterns and `$180k` floor if you want different targets

## Daily use

```bash
python3 -m hunter scan          # fetch, filter, queue
python3 -m hunter serve         # review UI at http://127.0.0.1:8765
python3 -m hunter list          # queue as a table
python3 -m hunter approve <id>  # writes a tailored resume
python3 -m hunter apply <id>    # headed browser; you click Submit
python3 -m hunter reject <id>
python3 -m hunter boards        # probe ATS boards for dead slugs
```

**Approve + open apply assist** in the UI marks the job approved, then launches the filled browser. You still click submit.

## Weekday batches (macOS)

```bash
bash scripts/install_launchd.sh
```

That installs weekday scans at 8:00 / 12:00 / 16:00 / 20:00 and a KeepAlive review UI. Scans only enqueue work. You still approve before any apply assist.

## Slack notifications

Scans can post with a Slack app via `chat.postMessage`. Copy `.env.example` to `.env` and fill `SLACK_BOT_TOKEN` / `SLACK_CHANNEL`. Test with `python3 -m hunter slack-test`.

## LinkedIn / Indeed

- **LinkedIn:** scraping and Easy Apply automation violate LinkedIn’s terms. Use the search links on the review UI, then queue a listing with `python3 -m hunter add <url>`.
- **Indeed:** the public RSS feed is retired. Use the search links, or paste a listing URL via `python3 -m hunter add <url>`.
- **Adzuna (optional):** set `ADZUNA_APP_ID` and `ADZUNA_APP_KEY` in `.env`.

## Guardrails

- Apply assist never clicks Submit.
- Roles stay queued until you approve or reject them.
- Secrets live in `.env` (gitignored). The local SQLite database is gitignored too.
