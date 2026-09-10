"""Maps what a job asks for onto what is actually on the master resume.

The old tailoring read tool names out of the job posting and asserted them as
experience, which put tools on a resume that never listed them. Everything here
is grounded the other way round: claims come from the master resume, and a
posting can only decide which of them to lead with, never add to them.

Edit the evidence strings so they stay true of *your* resume. The sample values
match profile/master_resume.md.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

from hunter.config import MASTER_RESUME_MD


@dataclass(frozen=True)
class Capability:
    key: str
    # Patterns that indicate a posting cares about this.
    cues: tuple[str, ...]
    # Gerund phrase, usable mid-sentence.
    headline: str
    # Past-tense clause with concrete detail, drawn from the master resume.
    evidence: str
    scopes: tuple[str, ...] = ("ic", "lead", "director")
    weight: float = 1.0


CAPABILITIES: tuple[Capability, ...] = (
    Capability(
        key="telemetry",
        cues=(r"telemetry", r"event (?:data|tracking|schema|pipeline)", r"instrumentation",
              r"clickstream", r"tracking plan", r"schema design"),
        headline="telemetry and schema design",
        evidence=(
            "designed event schemas and shared KPI models Helio Retail reported against "
            "so revenue, retention and conversion meant the same thing in every Looker explore"
        ),
        weight=1.3,
    ),
    Capability(
        key="pipelines",
        cues=(r"pipeline", r"\betl\b", r"\belt\b", r"ingestion", r"data engineering",
              r"orchestration", r"streaming", r"batch"),
        headline="pipeline engineering",
        evidence=(
            "owned production pipelines across two stacks — Airflow DAGs into Snowflake at "
            "Helio Retail, and Redshift models at Orbit Media"
        ),
        weight=1.2,
    ),
    Capability(
        key="modeling",
        cues=(r"data model", r"dimensional model", r"star schema", r"semantic layer",
              r"metrics layer", r"warehouse design", r"single source of truth"),
        headline="modeling and metric definition",
        evidence=(
            "developed the shared metric definitions that standardized revenue, retention and "
            "conversion across product, finance and marketing at Helio Retail"
        ),
        weight=1.25,
    ),
    Capability(
        key="self_serve",
        cues=(r"self[- ]serve", r"self[- ]service", r"dashboard", r"\bbi\b",
              r"business intelligence", r"reporting layer", r"data product", r"visuali[sz]ation"),
        headline="self-serve reporting",
        evidence=(
            "built the self-serve Looker layer product and finance ran on daily, having earlier "
            "delivered Tableau reporting to executives at Orbit Media"
        ),
        weight=1.2,
    ),
    Capability(
        key="data_quality",
        cues=(r"data quality", r"observability", r"validation", r"monitoring", r"alerting",
              r"reliability", r"trust(?:ed|worthy)? data", r"accuracy"),
        headline="data quality and observability",
        evidence=(
            "replaced ad-hoc warehouse extracts with tested incremental dbt models so dashboard "
            "builds stopped scanning raw event tables, and set tests so reported numbers stayed trustworthy"
        ),
        weight=1.15,
    ),
    Capability(
        key="experimentation",
        cues=(r"a/?b test", r"experimentation", r"causal", r"incrementality", r"holdout"),
        headline="experimentation support",
        evidence=(
            "partnered with product managers on A/B testing and made sure the telemetry "
            "actually supported the decisions the tests were meant to inform"
        ),
        weight=1.1,
    ),
    Capability(
        key="leadership",
        cues=(r"\blead\b", r"manage", r"mentor", r"coach", r"hiring", r"people manage",
              r"team of", r"direct report", r"grow the team", r"player[- ]coach"),
        headline="team leadership",
        evidence=(
            "led a team of 4 analysts at Orbit Media, setting priorities, mentoring, and the "
            "quality bar on numbers leadership used"
        ),
        scopes=("lead", "director"),
        weight=1.35,
    ),
    Capability(
        key="stakeholders",
        cues=(r"stakeholder", r"cross[- ]functional", r"partner with", r"business partner",
              r"influence", r"executive", r"leadership team", r"communicate"),
        headline="cross-functional partnership",
        evidence=(
            "acted as the analytics partner to product and finance, turning their questions "
            "into models and reporting they could run without me"
        ),
        weight=1.05,
    ),
    Capability(
        key="ai",
        cues=(r"\bai\b", r"\bllm\b", r"generative", r"genai", r"copilot", r"prompt",
              r"machine learning", r"agent"),
        headline="AI-assisted analytics workflows",
        evidence=(
            "leaned on LLM-assisted SQL workflows to compress pipeline checks and root-cause "
            "analysis, cutting work that used to take days down to hours"
        ),
        weight=1.1,
    ),
    Capability(
        key="migration",
        cues=(r"migrat", r"modern(?:ize|isation|ization)", r"re[- ]?platform", r"legacy",
              r"consolidat", r"lift and shift"),
        headline="platform migration",
        evidence=(
            "moved reporting off hand-built spreadsheet extracts onto tested warehouse models "
            "without breaking the dashboards the business depended on"
        ),
        weight=1.0,
    ),
    Capability(
        key="efficiency",
        cues=(r"cost", r"efficien", r"optimi[sz]", r"scale", r"performance", r"roi",
              r"automat"),
        headline="cost and efficiency work",
        evidence=(
            "cut reporting cycle time by automating extracts that had been assembled by hand "
            "each week"
        ),
        weight=1.0,
    ),
    Capability(
        key="standardization",
        cues=(r"standardi[sz]", r"harmoni[sz]", r"governance", r"consistency", r"definitions",
              r"taxonomy", r"catalog"),
        headline="metric standardization",
        evidence=(
            "led a metric harmonization effort across three business units so performance was "
            "finally comparable"
        ),
        weight=1.05,
    ),
    Capability(
        key="lifecycle",
        cues=(r"churn", r"retention", r"engagement", r"monetization", r"economy",
              r"lifetime value", r"\bltv\b", r"funnel", r"cohort"),
        headline="player and customer behaviour analysis",
        evidence=(
            "ran retention and funnel analysis that shaped roadmap decisions and surfaced "
            "where the population was leaking"
        ),
        weight=1.0,
    ),
    Capability(
        key="automation",
        cues=(r"automat", r"scheduled report", r"alerting", r"slack", r"daily report",
              r"operational reporting"),
        headline="automated operational reporting",
        evidence=(
            "kept hourly and daily KPI delivery running through Slack and email so operators "
            "never had to go looking for the numbers"
        ),
        weight=0.95,
    ),
)

# Only tools listed on the master resume may appear. The pattern is how a
# posting refers to it; the key is how it is written on the resume.
TOOL_PATTERNS: dict[str, str] = {
    "SQL": r"\bsql\b",
    "Python": r"\bpython\b",
    "dbt": r"\bdbt\b",
    "Snowflake": r"\bsnowflake\b",
    "Looker": r"\blooker\b",
    "Airflow": r"\bairflow\b",
    "AWS Redshift": r"\bredshift\b",
    "Tableau": r"\btableau\b",
    "Excel": r"\bexcel\b",
    "Git": r"\bgit\b",
    "Claude Code": r"\bclaude\b",
    "Cursor": r"\bcursor\b",
}

# Frequently requested tools that are absent from the sample resume. Never
# written into a document; surfaced so you know the gap before applying.
GAP_PATTERNS: dict[str, str] = {
    "BigQuery": r"\bbig ?query\b",
    "Databricks": r"\bdatabricks\b",
    "Kafka": r"\bkafka\b",
    "Fivetran": r"\bfivetran\b",
    "Airbyte": r"\bairbyte\b",
    "Spark": r"\bspark\b",
    "Iceberg": r"\biceberg\b",
    "Scala": r"\bscala\b",
    "Go": r"\bgolang\b",
    "Kubernetes": r"\bkubernetes\b|\bk8s\b",
    "Terraform": r"\bterraform\b",
}

DIRECTOR_RE = re.compile(r"\b(director|head of|vp|vice president|chief)\b", re.IGNORECASE)
LEAD_RE = re.compile(r"\b(manager|lead|principal)\b", re.IGNORECASE)


def owned_tools() -> set[str]:
    """Tools named in the master resume, so claims cannot drift from the source."""
    text = MASTER_RESUME_MD.read_text()
    owned: set[str] = set()
    for line in text.splitlines():
        stripped = line.strip().lstrip("- ")
        for prefix in ("Skills:", "Technologies used:"):
            if stripped.lower().startswith(prefix.lower()):
                body = stripped.split(":", 1)[1]
                owned.update(part.strip() for part in body.split(",") if part.strip())
    return owned


def job_scope(title: str) -> str:
    if DIRECTOR_RE.search(title or ""):
        return "director"
    if LEAD_RE.search(title or ""):
        return "lead"
    return "ic"


# Used when a posting is too thin to rank anything, which is common for Workday
# listings that expose a title and little else.
FALLBACK_ORDER = ("telemetry", "modeling", "self_serve", "pipelines", "leadership", "stakeholders")


def rank_capabilities(
    title: str, description: str, scope: str, minimum: int = 3
) -> list[Capability]:
    """Order capabilities by how much this posting actually asks for them."""
    title_text = (title or "").lower()
    body = (description or "").lower()
    scored: list[tuple[float, int, Capability]] = []
    for index, cap in enumerate(CAPABILITIES):
        if scope not in cap.scopes:
            continue
        hits = 0
        in_title = False
        for cue in cap.cues:
            found = len(re.findall(cue, body, re.IGNORECASE))
            hits += found
            if re.search(cue, title_text, re.IGNORECASE):
                in_title = True
        if not hits and not in_title:
            continue
        # Diminishing returns: ten mentions of "pipeline" is not ten times the
        # signal of one, but a cue in the title is a strong statement of intent.
        score = cap.weight * (1 + min(hits, 8) ** 0.5)
        if in_title:
            score += 2.0
        scored.append((score, -index, cap))
    scored.sort(reverse=True)
    ranked = [cap for _, _, cap in scored]
    # Thin postings (Workday especially) often have a title and no body.
    # Still lead with true, scope-appropriate work rather than a generic blurb.
    if len(ranked) < minimum:
        by_key = {cap.key: cap for cap in CAPABILITIES if scope in cap.scopes}
        for key in FALLBACK_ORDER:
            cap = by_key.get(key)
            if cap and cap not in ranked:
                ranked.append(cap)
            if len(ranked) >= minimum:
                break
    return ranked


TITLE_STOP = {
    "senior",
    "sr",
    "staff",
    "principal",
    "junior",
    "ii",
    "iii",
    "iv",
    "remote",
    "hybrid",
    "onsite",
    "office",
    "united",
    "states",
    "usa",
    "the",
    "and",
    "for",
    "with",
    "from",
    "into",
}

# Single tokens that are a job family. Used to keep the opening sentence from
# announcing the posting; not used to scrub the body, where "director" is often
# a title you have actually held.
ROLE_SINGLES = {
    "director",
    "manager",
    "engineer",
    "analyst",
    "scientist",
    "architect",
    "consultant",
    "specialist",
    "head",
    "intern",
}


def title_echo_needles(title: str) -> list[str]:
    """Phrases that would make a summary sound like it was written for this posting."""
    if not title:
        return []
    needles = [re.sub(r"\s+", " ", title.lower()).strip()]
    for chunk in re.split(r"[,|/–—]+", title):
        words = [
            word
            for word in re.findall(r"[a-z0-9]+", chunk.lower())
            if word not in TITLE_STOP and len(word) > 2
        ]
        if len(words) >= 2:
            needles.append(" ".join(words))
            needles.extend(" ".join(words[i : i + 2]) for i in range(len(words) - 1))
        elif words and words[0] in ROLE_SINGLES:
            needles.append(words[0])
    skip = {"data", "product", "business", "technical", "global", "team"}
    # Field names that appear on a typical analytics resume in the ordinary course.
    # Flagging them would reject any summary that mentions his actual work.
    generic = {
        "data engineering",
        "data science",
        "software engineer",
        "data platform",
        "business intelligence",
        "data analyst",
        "analytics engineering",
    }
    distinctive = []
    for needle in needles:
        if not needle or needle in skip or needle in generic or len(needle) < 4:
            continue
        words = needle.split()
        if len(words) == 1 or any(word in ROLE_SINGLES for word in words):
            distinctive.append(needle)
        elif needle == re.sub(r"\s+", " ", title.lower()).strip():
            distinctive.append(needle)
    return list(dict.fromkeys(distinctive))


def echoes_title(text: str, title: str, *, opening: bool = False) -> bool:
    """True when `text` restates the posting rather than the applicant's work.

    Multi-word needles are always checked. Single role words ('engineer',
    'director') are only checked in an opening sentence, where they read as
    'I am the thing you are hiring'.
    """
    lowered = (text or "").lower()
    if title and title.lower() in lowered:
        return True
    for needle in title_echo_needles(title):
        if " " not in needle and not opening:
            continue
        if re.search(rf"\b{re.escape(needle)}\b", lowered):
            return True
    return False


def matched_tools(description: str, title: str = "") -> list[str]:
    """Tools this posting mentions that are actually on the master resume."""
    blob = f"{title} {description}"
    owned = owned_tools()
    hits = []
    for label, pattern in TOOL_PATTERNS.items():
        if label in owned and re.search(pattern, blob, re.IGNORECASE):
            hits.append(label)
    return hits


def gap_tools(description: str, title: str = "") -> list[str]:
    """Requested tools absent from the resume. Shown so you can see the gap."""
    blob = f"{title} {description}"
    return [
        label
        for label, pattern in GAP_PATTERNS.items()
        if re.search(pattern, blob, re.IGNORECASE)
    ]


def variant(seed_text: str, options: list[str]) -> str:
    """Deterministic choice, so the same posting always yields the same resume."""
    if not options:
        return ""
    digest = hashlib.sha256(seed_text.encode()).hexdigest()
    return options[int(digest[:8], 16) % len(options)]
