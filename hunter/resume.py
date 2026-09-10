from __future__ import annotations

import json
import re
from pathlib import Path

from docx import Document
from docx.shared import Inches, Pt

from hunter.config import (
    CONTACT_PATH,
    MASTER_RESUME_DOCX,
    MASTER_RESUME_MD,
    OPENAI_API_KEY,
    OPENAI_MODEL,
    TAILORED_DIR,
)
from hunter.evidence import (
    echoes_title,
    gap_tools,
    job_scope,
    matched_tools,
    owned_tools,
    rank_capabilities,
    title_echo_needles,
    variant,
)

def _contact() -> dict:
    return json.loads(CONTACT_PATH.read_text())


def _master_text() -> str:
    return MASTER_RESUME_MD.read_text()


# Identity first, never the posting's job family. "Analytics engineer with…"
# for an Analytics Engineer role is the thing a recruiter spots immediately.
# Rewrite these to match profile/master_resume.md. They are the opening lines
# of a tailored summary — they must be true of you, not of the sample resume.
IDENTITY = {
    "ic": [
        "Twelve years on the path from raw events to the number a decision gets made on, most recently inside a retail data team.",
        "Most of my career has been the stretch between instrumentation and the dashboard leadership actually opens. The last five years of that were at Helio Retail.",
        "I have spent twelve years making production data trustworthy enough to run a business on, latterly as a senior analytics engineer at Helio Retail.",
        "The through-line of the last twelve years is getting from a messy event stream to a number someone will actually use. I did that most recently at Helio Retail.",
    ],
    "lead": [
        "I have spent twelve years in this discipline and still write the SQL — the last chapter of that was leading analytics at Orbit Media.",
        "Twelve years in the work, including the years I ran analytics for a media company while staying in the warehouse myself.",
        "Most of my career has been the layer between instrumentation and the number leadership uses. Latterly that included leading the function at Orbit Media.",
        "I come from twelve years of warehouse and analytics work, the recent stretch of it as a senior analytics engineer after leading the function at Orbit Media.",
    ],
    "director": [
        "I spent years owning analytics for a media company, still close enough to the warehouse to feel the quality problems firsthand.",
        "Twelve years across analytics and data engineering, including a stretch leading that function end to end at Orbit Media.",
        "I have spent twelve years making production data trustworthy enough to run a business on, including the years I owned that bar for a team of analysts.",
        "The last chapter of a twelve-year stretch in this work was senior analytics engineering after leading the function at Orbit Media, still writing the SQL.",
    ],
}

# How two overlapping capabilities get said as one motion, not two stacked claims.
BLEND_TWO = [
    "I {e1}, and I {e2}.",
    "I {e1}. The same years produced the other half of this: I {e2}.",
    "{e1_cap} — and because that only holds if the foundations do, I {e2}.",
]

BLEND_THIRD = [
    "Alongside that I {e3}.",
    "That sat next to {h3}: I {e3}.",
    "The same stretch included {h3} — I {e3}.",
]

# Only tools the posting actually named. Padding the list with SQL/Python/Tableau
# on every resume is how tailoring starts to look like a keyword dump.
TOOL_CLOSES = [
    "I already do this in {tools}.",
    "That work already lives in {tools}.",
    "{tools_cap} are already the daily instruments.",
]


def _join(items: list[str]) -> str:
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + " and " + items[-1]


def _capitalize(text: str) -> str:
    return text[:1].upper() + text[1:] if text else text


def _pick_opening(scope: str, title: str, seed: str) -> str:
    pool = [line for line in IDENTITY[scope] if not echoes_title(line, title, opening=True)]
    if not pool:
        pool = IDENTITY[scope]
    return variant(seed, pool)


def _blend(ranked, seed: str) -> list[str]:
    """Turn ranked overlaps into prose, not a list of evidence sentences."""
    if not ranked:
        return []
    if len(ranked) == 1:
        cap = ranked[0]
        return [_capitalize(cap.evidence) + "."]

    first, second = ranked[0], ranked[1]
    two = variant(seed + "blend", BLEND_TWO).format(
        h1=first.headline,
        h2=second.headline,
        e1=first.evidence,
        e2=second.evidence,
        e1_cap=_capitalize(first.evidence),
    )
    sentences = [two]
    if len(ranked) >= 3:
        third = ranked[2]
        sentences.append(
            variant(seed + "third", BLEND_THIRD).format(
                h3=third.headline, e3=third.evidence
            )
        )
    return sentences


def compose_summary(title: str, company: str, description: str) -> str:
    """Lead with the overlapping work, never the job title.

    The posting only chooses which true things get said, and in what order.
    A recruiter should be able to read the paragraph without knowing which
    requisition it was written against.
    """
    scope = job_scope(title)
    ranked = rank_capabilities(title, description, scope)
    tools = matched_tools(description, title)[:4]

    # Deterministic first, then rotate phrasing if a draft still echoes the title.
    last = ""
    for salt in range(6):
        seed = f"{company}|{title}|{salt}"
        sentences = [_pick_opening(scope, title, seed)]
        sentences.extend(_blend(ranked[:3], seed))
        if len(tools) >= 2:
            frame = variant(seed + "tools", TOOL_CLOSES)
            sentences.append(
                frame.format(tools=_join(tools), tools_cap=_capitalize(_join(tools)))
            )
        last = _enforce_length(" ".join(sentences), sentences)
        if not summary_problems(last, title, description):
            return last
    return last


def _enforce_length(summary: str, sentences: list[str], limit: int = 135) -> str:
    # Trim from the middle rather than the end: the opening establishes who you
    # are and the tools line carries the keyword overlap an ATS looks for.
    while len(summary.split()) > limit and len(sentences) > 2:
        sentences.pop(-2)
        summary = " ".join(sentences)
    return summary


BANNED_PHRASES = (
    "seeking",
    "i am applying",
    "i'm applying",
    "looking for a role",
    "this role",
    "your team",
    "the position",
    "ideal candidate",
    "perfect fit",
)


def summary_problems(summary: str, title: str, description: str) -> list[str]:
    """Reasons a candidate summary is unusable. Empty list means it is fine."""
    problems = []
    lowered = (summary or "").lower()
    if not summary or len(summary.split()) < 45:
        problems.append("too short")
    if len(summary.split()) > 150:
        problems.append("too long")
    if title and title.lower() in lowered:
        problems.append("echoes the job title verbatim")
    first = re.split(r"(?<=[.!?])\s+", summary.strip(), maxsplit=1)[0]
    if echoes_title(first, title, opening=True):
        problems.append("opening restates the job family")
    for needle in title_echo_needles(title):
        if " " in needle and re.search(rf"\b{re.escape(needle)}\b", lowered):
            problems.append(f"echoes title phrase {needle!r}")
    for phrase in BANNED_PHRASES:
        if phrase in lowered:
            problems.append(f"uses filler phrase {phrase!r}")
    # The decisive check: no tool may appear that the master resume does not.
    owned = {tool.lower() for tool in owned_tools()}
    for tool in gap_tools(description, title):
        if tool.lower() in lowered and tool.lower() not in owned:
            problems.append(f"claims {tool}, which is not on the master resume")
    return list(dict.fromkeys(problems))


def _llm_summary(
    title: str, company: str, description: str, tools: list[str], claims: str
) -> str | None:
    if not OPENAI_API_KEY:
        return None
    import httpx

    master = _master_text()
    prompt = (
        "Rewrite this resume's summary so it leads with the work that overlaps the posting, "
        "without ever sounding like it was written for the posting.\n\n"
        "Hard rules:\n"
        "- Never name or paraphrase the job title. Do not open with a job family "
        "('analytics engineer', 'data engineering manager', 'director').\n"
        "- Never name the hiring company or the fact that this is an application.\n"
        "- Never write 'seeking', 'this role', 'ideal candidate', 'targeting', or similar.\n"
        "- Only use the experience claims listed below. Reorder and blend them; do not invent.\n"
        "- Only name tools that appear in the resume. Adding any other tool is a failure.\n"
        "- Write one paragraph of 85-125 words. Past tense, concrete, specific.\n"
        "- It should read as a career summary, not a cover letter.\n\n"
        f"Do not use these phrases: {', '.join(title_echo_needles(title)) or 'none'}\n"
        f"Shared tools you may mention: {', '.join(tools) or 'none'}\n"
        f"Experience claims you may use:\n{claims}\n\n"
        f"JOB DESCRIPTION (for emphasis only):\n{description[:4000]}\n\nRESUME:\n{master}"
    )
    try:
        with httpx.Client(timeout=45.0) as client:
            resp = client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
                json={
                    "model": OPENAI_MODEL,
                    "messages": [
                        {
                            "role": "system",
                            "content": (
                                "You tailor resumes honestly. You never add a tool, employer or "
                                "achievement that is not already in the source resume."
                            ),
                        },
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": 0.4,
                },
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"].strip()
    except Exception:
        return None


def _cover_note(title: str, company: str, description: str) -> str:
    """Opens on lived work, not on the requisition."""
    scope = job_scope(title)
    ranked = rank_capabilities(title, description, scope)
    lead = ranked[0] if ranked else None
    tools = matched_tools(description, title)
    seed = f"{company}|{title}|note"

    if lead:
        hook = f"I {lead.evidence}."
    else:
        hook = (
            "I spent the last five years building warehouse models and self-serve reporting, "
            "from event instrumentation through the dashboards leadership ran on."
        )

    background = (
        "Most recently I was a senior analytics engineer at Helio Retail, after leading "
        "analytics at Orbit Media."
    )
    tool_line = f" I already work in {_join(tools[:4])}." if tools else ""
    return f"{hook} {background}{tool_line} Happy to talk whenever suits."


def _replace_text(paragraph, text: str) -> None:
    """Swap paragraph text while keeping the first run's formatting."""
    for run in paragraph.runs[1:]:
        run.text = ""
    if paragraph.runs:
        paragraph.runs[0].text = text
    else:
        paragraph.add_run(text)


def _find_summary_paragraph(document):
    """Locate the summary body by structure, not by its current wording.

    Anchoring on the literal opening words meant the tailoring silently stopped
    working the moment that sentence changed.
    """
    paragraphs = document.paragraphs
    for index, para in enumerate(paragraphs):
        if para.text.strip().rstrip(":").upper() != "SUMMARY":
            continue
        for candidate in paragraphs[index + 1 : index + 5]:
            if len(candidate.text.strip()) > 120:
                return candidate
    # Fall back to the first substantial paragraph before the experience block.
    for para in paragraphs[:12]:
        text = para.text.strip()
        if text.upper().startswith("EXPERIENCE"):
            break
        if len(text) > 200:
            return para
    return None


def write_tailored_docx(job: dict, summary: str, keywords: list[str], dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if MASTER_RESUME_DOCX.exists():
        document = Document(str(MASTER_RESUME_DOCX))
        target = _find_summary_paragraph(document)
        if target is None:
            raise RuntimeError(
                "Could not locate the summary paragraph in the master resume; "
                "refusing to guess and corrupt the document."
            )
        _replace_text(target, summary)
        # Promote matching skills toward the front of the skills paragraph.
        if keywords:
            for para in document.paragraphs:
                if para.text.startswith("Skills:"):
                    rest = para.text[len("Skills:") :].strip()
                    parts = [p.strip() for p in rest.split(",") if p.strip()]
                    # Only reorder. Nothing is ever added to the skills line,
                    # so it cannot drift from the master resume.
                    promoted = [k for k in keywords if any(k.lower() == p.lower() for p in parts)]
                    others = [p for p in parts if p.lower() not in {k.lower() for k in promoted}]
                    _replace_text(para, "Skills: " + ", ".join(promoted + others))
                    break
        document.save(str(dest))
        return

    contact = _contact()
    linkedin = (
        (contact.get("linkedin") or "")
        .replace("https://", "")
        .replace("http://", "")
        .rstrip("/")
    )
    document = Document()
    for section in document.sections:
        section.top_margin = Inches(0.6)
        section.bottom_margin = Inches(0.6)
    title = document.add_paragraph(contact["full_name"])
    title.runs[0].font.size = Pt(18)
    document.add_paragraph(
        f"P: {contact['phone_display']} | {contact['email']} | {linkedin}"
    )
    document.add_paragraph("SUMMARY")
    document.add_paragraph(summary)
    document.add_paragraph(_master_text())
    document.save(str(dest))


def build_tailoring(job: dict) -> dict:
    """Everything the tailoring decided, without writing a file."""
    title = job.get("title") or ""
    company = job.get("company") or ""
    description = job.get("description") or ""

    tools = matched_tools(description, title)
    gaps = gap_tools(description, title)
    ranked = rank_capabilities(title, description, job_scope(title))
    claims = "\n".join(f"- {cap.evidence}" for cap in ranked[:5])
    source = "composed"

    summary = _llm_summary(title, company, description, tools, claims)
    if summary:
        problems = summary_problems(summary, title, description)
        if problems:
            summary = None
        else:
            source = "llm"
    if not summary:
        summary = compose_summary(title, company, description)

    scope = job_scope(title)
    return {
        "summary": summary,
        "cover_note": _cover_note(title, company, description),
        "keywords": tools,
        "gaps": gaps,
        "scope": scope,
        "source": source,
        "emphasis": [cap.key for cap in rank_capabilities(title, description, scope)[:4]],
    }


def tailor_for_job(job: dict) -> dict:
    tailoring = build_tailoring(job)
    slug = re.sub(r"[^a-z0-9]+", "-", f"{job.get('company','')}-{job.get('title','')}".lower()).strip("-")[:60]
    dest = TAILORED_DIR / f"{job['id']}-{slug or 'role'}.docx"
    write_tailored_docx(job, tailoring["summary"], tailoring["keywords"], dest)
    return {"tailored_resume_path": str(dest), **tailoring}
