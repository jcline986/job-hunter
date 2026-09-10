# Agent context

Job-search assistant. See `README.md` for what it does and how to run it. This file covers the things that are easy to get wrong.

The `profile/` files in a fresh clone are a **fictional sample**. Do not treat them as a real person’s resume.

## One live package

`python -m hunter` is the product. `scripts/scan.sh` and `scripts/serve.sh` invoke it, and those are what the LaunchAgents call.

## Resume files

| Consumer | Master file |
| --- | --- |
| Tailoring copy | `profile/master_resume.md` |
| Word styling | `profile/resume_template.docx` |
| Apply-form identity | `profile/contact.json` |

`write_tailored_docx()` in `hunter/resume.py` opens the `.docx` and edits the summary (and reorders skills) in place, so every tailored resume inherits its styling. If you replace the template, keep a paragraph whose heading is `SUMMARY` followed by a body longer than 120 characters, or tailoring will refuse to write.

When editing that `.docx`, use `python-docx`. Regex over `word/document.xml` can clone the wrong paragraphs and duplicate headings.

Claims in `hunter/evidence.py` (`CAPABILITIES`) and opening lines in `hunter/resume.py` (`IDENTITY`) must stay true of the master resume. Tailoring will not add tools that are missing from the Skills line.

## Guardrails — intentional, not gaps

- **Apply assist never submits.** It fills what it can, then stops for a human to click Submit. Do not automate that click.
- **No LinkedIn or Indeed scraping.** LinkedIn's terms forbid it and Indeed's RSS feed is retired. Both are handled by opening search links for manual use.
- Roles are queued for approval; nothing is sent without an explicit decision.

## Data and secrets

`data/` and `.env` are gitignored. `.env` holds Slack, Adzuna, and OpenAI credentials — don't print or commit them.

## Commands

```bash
source .venv/bin/activate
python3 -m hunter scan
python3 -m hunter serve
python3 -m hunter list
python3 -m hunter approve <id>
python3 -m hunter apply <id>
python3 -m hunter boards
bash scripts/install_launchd.sh
```
