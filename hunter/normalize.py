from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any

SALARY_RE = re.compile(
    r"""
    # Never start mid-number: without this, "SEK 1,054,294" matched the inner
    # "54,294" and escaped the foreign-currency check.
    (?<![\d,.])
    (?P<currency>\$|usd\s*)?
    # k-suffixed form first: otherwise "150k" matches as bare "150" and the
    # range separator is never reached, dropping the low end of the band.
    (?P<amount>\d{2,3}k|\d{2,3}(?:,\d{3})?(?:\.\d+)?)
    (?:\s*(?:-|to|–|—)\s*(?:\$|usd\s*)?(?P<amount2>\d{2,3}k|\d{2,3}(?:,\d{3})?(?:\.\d+)?))?
    \s*(?P<unit>k|thousand)?
    \s*(?P<period>/?\s*(?:yr|year|annually|per\s*year|a\s*year))?
    """,
    re.IGNORECASE | re.VERBOSE,
)

# Retirement plans, equity vesting years and similar numbers masquerade as pay.
RETIREMENT_RE = re.compile(r"\b40[1237]\s*\(?\s*[kbm]\s*\)?", re.IGNORECASE)

# Plausible annual base salary bounds for these roles, in USD.
SALARY_FLOOR = 40_000
SALARY_CEILING = 1_200_000

# A foreign currency code just before the number means this band is not USD.
# Grafana's Sweden postings quote "SEK 878,578", which read as $878k.
NON_USD = re.compile(
    r"(?:SEK|EUR|GBP|CAD|AUD|NZD|CHF|DKK|NOK|PLN|INR|JPY|BRL|MXN|ZAR|SGD|HKD|"
    r"CNY|RUB|TRY|ILS|AED|KRW|THB|IDR|PHP|VND|kr|zł|£|€|₹|¥|₪|C\$|A\$)\s*$",
    re.IGNORECASE,
)
HTML_TAG = re.compile(r"<[^>]+>")


def _preceded_by_foreign_currency(text: str, start: int) -> bool:
    lead = HTML_TAG.sub(" ", text[max(0, start - 60) : start])
    return bool(NON_USD.search(re.sub(r"\s+", " ", lead)))


COMP_CUE = re.compile(
    r"\b(base\s+salary|salary\s+range|pay\s+range|compensation\s+range|"
    r"base\s+pay|annual\s+salary|target\s+(?:salary|compensation)|"
    r"expected\s+(?:salary|compensation)|salary|compensation|\bOTE\b)\b",
    re.IGNORECASE,
)

REMOTE_RE = re.compile(
    r"\b(remote|work from home|wfh|distributed|anywhere in (the )?us|united states remote)\b",
    re.IGNORECASE,
)
HYBRID_ONLY_RE = re.compile(r"\b(hybrid|on[- ]site|in[- ]office|office[- ]based)\b", re.IGNORECASE)
US_ONLY_HINT = re.compile(
    r"\b(united states|u\.s\.a?|usa|us-based|must be (located|based) in the (us|united states))\b",
    re.IGNORECASE,
)

US_STATES = (
    "alabama|alaska|arizona|arkansas|california|colorado|connecticut|delaware|"
    "florida|georgia|hawaii|idaho|illinois|indiana|iowa|kansas|kentucky|"
    "louisiana|maine|maryland|massachusetts|michigan|minnesota|mississippi|"
    "missouri|montana|nebraska|nevada|new hampshire|new jersey|new mexico|"
    "new york|north carolina|north dakota|ohio|oklahoma|oregon|pennsylvania|"
    "rhode island|south carolina|south dakota|tennessee|texas|utah|vermont|"
    "virginia|washington|west virginia|wisconsin|wyoming"
)

# Unambiguous US cities only. Birmingham, Cambridge and Manchester also name
# UK cities, so they are left out.
US_CITIES = (
    "san francisco|new york|nyc|los angeles|chicago|boston|seattle|austin|"
    "denver|atlanta|miami|dallas|houston|philadelphia|phoenix|san diego|"
    "portland|san jose|nashville|charlotte|minneapolis|detroit|pittsburgh|"
    "salt lake city|las vegas|orlando|tampa|raleigh|durham|columbus|"
    "kansas city|st\\. louis|saint louis|cincinnati|cleveland|indianapolis|"
    "milwaukee|sacramento|brooklyn|palo alto|mountain view|menlo park|"
    "sunnyvale|santa clara|santa monica|redmond|bellevue|boulder|ann arbor|"
    "chapel hill|fort worth|san antonio|baltimore|washington[, ]+d\\.?c\\.?"
)

US_MARKERS = re.compile(
    rf"\b(united states|u\.s\.a?\.?|usa|us[- ]based|us[- ]remote|remote[-, ]+us\b|"
    rf"nationwide|anywhere in the us|{US_STATES}|{US_CITIES})\b",
    re.IGNORECASE,
)

# Country names and unambiguously foreign cities. City names shared with US
# places (Birmingham, Cambridge, Georgia the country) are deliberately omitted.
NON_US_MARKERS = re.compile(
    r"\b(canada|mexico|brazil|argentina|chile|colombia|peru|uruguay|costa rica|"
    r"united kingdom|u\.k\.|\buk\b|\bgb\b|england|scotland|wales|northern ireland|ireland|"
    r"france|germany|spain|portugal|italy|netherlands|belgium|luxembourg|"
    r"switzerland|austria|sweden|norway|denmark|finland|iceland|poland|"
    r"czechia|czech republic|slovakia|hungary|romania|bulgaria|serbia|croatia|"
    r"slovenia|estonia|latvia|lithuania|greece|cyprus|turkey|ukraine|russia|"
    r"israel|united arab emirates|dubai|abu dhabi|saudi arabia|qatar|egypt|"
    r"south africa|nigeria|ghana|kenya|morocco|india|pakistan|bangladesh|sri lanka|"
    r"china|hong kong|taiwan|japan|south korea|singapore|malaysia|thailand|"
    r"vietnam|philippines|indonesia|australia|new zealand|"
    r"emea|apac|latam|anz|europe|european union|\beu\b|nordics|benelux|dach|"
    r"iberia|oceania|south america|middle east|southeast asia|"
    r"london|dublin|cardiff|edinburgh|glasgow|paris|berlin|munich|m[uü]nchen|"
    r"hamburg|amsterdam|rotterdam|stockholm|"
    r"copenhagen|oslo|helsinki|warsaw|krakow|prague|budapest|bucharest|"
    r"belgrade|zagreb|athens|istanbul|tel aviv|jerusalem|bengaluru|bangalore|"
    r"mumbai|new delhi|gurugram|gurgaon|hyderabad|pune|chennai|noida|"
    r"sydney|melbourne|brisbane|perth|auckland|wellington|tokyo|osaka|seoul|"
    r"toronto|vancouver|montreal|ottawa|calgary|winnipeg|edmonton|"
    r"mexico city|guadalajara|monterrey|sao paulo|s\u00e3o paulo|rio de janeiro|"
    r"bogota|bogot\u00e1|buenos aires|lima|santiago|barcelona|madrid|valencia|"
    r"lisbon|porto|milan|rome|turin|zurich|geneva|vienna|brussels|antwerp|"
    r"cape town|johannesburg|lagos|nairobi|cairo|manila|jakarta|bangkok|"
    r"kuala lumpur|ho chi minh|hanoi|shanghai|beijing|shenzhen|taipei)\b",
    re.IGNORECASE,
)

# Only an explicit statement in the body should override an unknown location,
# and only when what follows names a foreign place. Matching the phrase alone
# flagged "This role is based in San Francisco, CA" as non-US.
LOCATION_CLAIM_RE = re.compile(
    r"\b(?:must be (?:located|based|a resident) in|this role is based in|"
    r"this position is based in|candidates must (?:be|reside) in)\b",
    re.IGNORECASE,
)
REGION_ONLY_RE = re.compile(
    r"\b(?:eu|uk|u\.k\.|emea|apac|latam|anz|canada|india|australia|nigeria|"
    r"ghana|kenya|philippines|poland|spain|germany|france|ireland|israel|"
    r"singapore|brazil|mexico|japan|south africa)[- ]only\b",
    re.IGNORECASE,
)
WORK_AUTH_RE = re.compile(
    r"\b(?:right to work|work (?:authori[sz]ation|permit)|"
    r"eligib(?:le|ility) to work|authori[sz]ed to work)\s+in\s+(?:the\s+)?",
    re.IGNORECASE,
)
US_EXCLUDED_RE = re.compile(
    r"\b(?:not (?:open|available|eligible) to (?:applicants? (?:in|from) )?(?:the )?(?:us|u\.s\.|united states)|"
    r"(?:us|u\.s\.|united states) applicants? (?:are )?not eligible|"
    r"cannot (?:hire|employ) (?:in|from) the (?:us|united states))\b",
    re.IGNORECASE,
)

TITLE_NEGATIVE = re.compile(
    r"\b(intern|internship|junior|associate analyst|help desk|call center)\b",
    re.IGNORECASE,
)

# Data science is a separate track. Excluded unless the title is itself an
# analytics engineering role that merely sits in a data science org.
SCIENCE_NEGATIVE = re.compile(r"\b(scientist|scientists|science|sciences)\b", re.IGNORECASE)


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_posted_at(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    if isinstance(value, (int, float)):
        ts = float(value)
        if ts > 1e12:
            ts /= 1000.0
        elif ts > 1e10:
            ts /= 1000.0
        try:
            return datetime.fromtimestamp(ts, tz=timezone.utc)
        except (OSError, OverflowError, ValueError):
            return None
    text = str(value).strip()
    if not text:
        return None
    if text.isdigit():
        return parse_posted_at(int(text))
    text = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def posted_age_hours(value: Any, now: datetime | None = None) -> float | None:
    posted = parse_posted_at(value)
    if posted is None:
        return None
    now = now or datetime.now(timezone.utc)
    return (now - posted).total_seconds() / 3600.0


def is_fresh(value: Any, max_age_hours: int, now: datetime | None = None) -> bool:
    age = posted_age_hours(value, now=now)
    if age is None:
        return True
    return age <= max_age_hours and age > -24


def posted_label(value: Any) -> str:
    posted = parse_posted_at(value)
    if posted is None:
        return "posted date unknown"
    age = posted_age_hours(posted)
    if age is None:
        return posted.strftime("%Y-%m-%d")
    if age < 24:
        hours = max(1, int(age))
        return f"posted {hours}h ago"
    days = int(age / 24)
    return f"posted {days}d ago ({posted.strftime('%Y-%m-%d')})"


TITLE_NOISE = re.compile(
    r"\b(remote|hybrid|onsite|on-site|us|usa|united states|contract|full[- ]time|"
    r"[ivx]+|\d+)\b|[^a-z0-9 ]",
    re.IGNORECASE,
)


def dedupe_key(title: str, company: str) -> str:
    """Company + title key so one role posted to several boards collapses."""
    def clean(value: str) -> str:
        value = TITLE_NOISE.sub(" ", (value or "").lower())
        return re.sub(r"\s+", " ", value).strip()

    company_clean = clean(company)
    title_clean = clean(title)
    if not company_clean or not title_clean:
        return ""
    return hashlib.sha256(f"{company_clean}|{title_clean}".encode()).hexdigest()[:24]


def fingerprint(source: str, url: str, title: str, company: str) -> str:
    raw = "|".join(
        [
            source.strip().lower(),
            (url or "").split("?")[0].strip().lower(),
            re.sub(r"\s+", " ", title).strip().lower(),
            re.sub(r"\s+", " ", company or "").strip().lower(),
        ]
    )
    return hashlib.sha256(raw.encode()).hexdigest()[:24]


def _to_annual(amount: str, unit: str | None) -> int | None:
    cleaned = amount.lower().replace(",", "")
    if cleaned.endswith("k"):
        value = float(cleaned[:-1]) * 1000
    else:
        value = float(cleaned)
        if unit and unit.lower() in {"k", "thousand"}:
            value *= 1000
    if value < 20_000 or value > 1_000_000:
        return None
    return int(value)


def parse_salary(text: str) -> tuple[int | None, int | None, str | None]:
    if not text:
        return None, None, None
    # "401(k)" otherwise parses as $401k and fakes a top-of-market range.
    text = RETIREMENT_RE.sub(" retirement plan ", text)

    # Anchor on compensation wording first. Scanning a whole job description
    # and keeping the largest number picks up revenue figures, customer counts
    # and multi-region bands, which produced $969k "salaries" for mid-level
    # engineering roles.
    for cue in COMP_CUE.finditer(text):
        window = text[cue.end() : cue.end() + 240]
        found = _scan_salary(window)
        if found[0] is not None:
            return found
    return _scan_salary(text, ranges_only=True)


def _scan_salary(
    text: str, ranges_only: bool = False
) -> tuple[int | None, int | None, str | None]:
    best: tuple[int | None, int | None] | None = None
    raw = None
    for match in SALARY_RE.finditer(text):
        if ranges_only and not match.group("amount2"):
            continue
        if not match.group("currency") and _preceded_by_foreign_currency(text, match.start()):
            continue
        amount = match.group("amount") or ""
        # Require an explicit money signal. Without this, incidental digit pairs
        # like "90-909" in a job ID were being read as a $909k salary.
        explicit = bool(
            match.group("currency")
            or match.group("unit")
            or "k" in amount.lower()
            or "," in amount
        )
        if not explicit:
            continue
        low = _to_annual(match.group("amount"), match.group("unit"))
        high = low
        if match.group("amount2"):
            high = _to_annual(match.group("amount2"), match.group("unit")) or low
        if low is None or not (SALARY_FLOOR <= low <= SALARY_CEILING):
            continue
        if high is not None and high > SALARY_CEILING:
            continue
        # First plausible band wins. Later numbers in a posting are usually
        # equity, bonus or a different region's range.
        best = (low, high)
        raw = match.group(0)
        break
    if not best:
        return None, None, None
    return best[0], best[1], raw


def is_remote_eligible(title: str, location: str, description: str) -> bool:
    blob = " ".join(filter(None, [title, location, description]))
    if REMOTE_RE.search(blob):
        return True
    loc = (location or "").lower()
    if loc in {"remote", "anywhere", "united states", "usa", "us"}:
        return True
    if "remote" in loc:
        return True
    return False


def _foreign_only_clause(text: str) -> bool:
    """True for 'Nigeria only', 'UK-only', and similar country locks."""
    if not text:
        return False
    if REGION_ONLY_RE.search(text):
        return True
    for match in NON_US_MARKERS.finditer(text):
        after = text[match.end() : match.end() + 8]
        if re.match(r"[- ]only\b", after, re.IGNORECASE):
            return True
    return False


def _foreign_work_auth(text: str) -> bool:
    for claim in WORK_AUTH_RE.finditer(text or ""):
        window = text[claim.end() : claim.end() + 80]
        if NON_US_MARKERS.search(window) and not US_MARKERS.search(window):
            return True
    return False


def us_eligible(title: str, location: str, description: str = "") -> bool:
    """True unless the posting is clearly tied to a non-US location.

    Deliberately asymmetric: an explicit US signal wins, a clear foreign signal
    loses, and anything ambiguous is kept. Dropping unknowns would discard the
    many postings whose location is just "Remote".
    """
    blob = " ".join(filter(None, [title, location]))
    if US_MARKERS.search(blob):
        return True
    if NON_US_MARKERS.search(blob):
        return False
    body = description or ""
    combined = " ".join(filter(None, [blob, body]))
    # Country-only badges belong in the location field, but aggregators often
    # leave that as "Remote" and put "Nigeria only" in the body instead.
    if _foreign_only_clause(combined):
        return False
    if US_EXCLUDED_RE.search(combined):
        return False
    if _foreign_work_auth(body):
        return False
    for claim in LOCATION_CLAIM_RE.finditer(body):
        window = body[claim.end() : claim.end() + 80]
        if NON_US_MARKERS.search(window) and not US_MARKERS.search(window):
            return False
    return True


def salary_status(min_comp: int, salary_min: int | None, salary_max: int | None) -> str:
    if salary_min is None and salary_max is None:
        return "unknown"
    top = salary_max or salary_min or 0
    if top >= min_comp:
        return "meets"
    return "below"


def title_matches(title: str, patterns: list[str]) -> bool:
    if TITLE_NEGATIVE.search(title or ""):
        return False
    text = title or ""
    return any(re.search(p, text, re.IGNORECASE) for p in patterns)


def dump_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)
