"""Remotive public API fetcher and field mapper."""

from __future__ import annotations

import json
import re
from urllib.request import Request, urlopen

from . import _SSL_CONTEXT, normalize_countries, sanitize_html, strip_html

API_URL = "https://remotive.com/api/remote-jobs"
USER_AGENT = "AgentHub/0.2 (+https://github.com/agent-hub)"
HOURS_PER_WORK_YEAR = 2080

# Matches patterns like: $90 - $150, $150,000 - $230,000, $150k - $230k
_SALARY_RE = re.compile(
    r"\$\s*([\d,]+(?:\.\d+)?)\s*([kK])?\s*"
    r"(?:-\s*\$?\s*([\d,]+(?:\.\d+)?)\s*([kK])?)?"
)


def parse_salary(text: str) -> tuple[float | None, float | None, str]:
    """Parse Remotive free-text salary into (min, max, period).

    Returns hourly values. Annual salaries are converted via /2080.
    """
    if not text or not text.strip():
        return None, None, "hour"

    is_hourly = "/hour" in text.lower() or "per hour" in text.lower()

    match = _SALARY_RE.search(text)
    if not match:
        return None, None, "hour"

    raw_min = float(match.group(1).replace(",", ""))
    if match.group(2):  # k suffix
        raw_min *= 1000

    raw_max = None
    if match.group(3):
        raw_max = float(match.group(3).replace(",", ""))
        if match.group(4):  # k suffix
            raw_max *= 1000

    if not is_hourly:
        raw_min = round(raw_min / HOURS_PER_WORK_YEAR, 2)
        if raw_max is not None:
            raw_max = round(raw_max / HOURS_PER_WORK_YEAR, 2)

    return raw_min, raw_max, "hour"


def map_job(raw: dict) -> dict:
    """Convert a single Remotive API entry to system JobInput-compatible dict."""
    salary_text = raw.get("salary") or ""
    comp_min, comp_max, period = parse_salary(salary_text)

    location = (raw.get("candidate_required_location") or "").strip()
    if not location or location.lower() in ("worldwide", "anywhere"):
        countries_allowed = ["GLOBAL"]
    else:
        countries_allowed = normalize_countries(
            [loc.strip() for loc in location.split(",") if loc.strip()]
        )

    tags = raw.get("tags") or []
    category = raw.get("category") or ""
    categories = [category] if category else list(tags)

    job_type = (raw.get("job_type") or "").lower()
    if job_type in ("contract", "freelance", "part_time"):
        employment_type = "part_time"
    else:
        employment_type = "part_time"  # Default for remote job board

    return {
        "source_job_id": str(raw.get("id", "")),
        "canonical_url": raw.get("url", ""),
        "title_original": raw.get("title", ""),
        "title_zh": None,
        "company_name": raw.get("company_name", ""),
        "description_original": sanitize_html(raw.get("description", "")),
        "description_zh": None,
        "employment_type": employment_type,
        "work_mode": "remote",
        "countries_allowed": countries_allowed,
        "timezone_requirements": [],
        "languages": [],
        "skills": list(tags),
        "categories": categories,
        "hours_per_week_min": None,
        "hours_per_week_max": None,
        "compensation_min": comp_min,
        "compensation_max": comp_max,
        "compensation_currency": "USD",
        "compensation_period": period,
        "published_at": raw.get("publication_date"),
        "quality_score": 0.75,
        "extraction_confidence": 0.7,
    }


def fetch(
    category: str | None = None,
    search: str | None = None,
    limit: int = 200,
) -> list[dict]:
    """Fetch raw job listings from the Remotive public API."""
    params = []
    if category:
        params.append(f"category={category}")
    if search:
        params.append(f"search={search}")
    if limit:
        params.append(f"limit={limit}")
    url = API_URL
    if params:
        url = f"{url}?{'&'.join(params)}"
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, context=_SSL_CONTEXT) as response:
        data = json.loads(response.read())
    return data.get("jobs", [])[:limit]
