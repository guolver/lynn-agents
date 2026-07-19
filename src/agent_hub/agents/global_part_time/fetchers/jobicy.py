"""Jobicy public API fetcher and field mapper.

Pure functions only — no dependency on service, repository, or framework.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from . import _SSL_CONTEXT, normalize_countries, sanitize_html, strip_html

__all__ = ["fetch", "map_job"]

HOURS_PER_WORK_YEAR = 2080

API_URL = "https://jobicy.com/api/v2/remote-jobs"
USER_AGENT = "AgentHub/0.2 (+https://github.com/agent-hub)"


def map_job(raw: dict) -> dict:
    """Convert a single Jobicy API entry to system JobInput-compatible dict."""
    salary_min = raw.get("salaryMin") or 0
    salary_max = raw.get("salaryMax") or 0
    salary_currency = raw.get("salaryCurrency") or "USD"
    salary_period = raw.get("salaryPeriod") or ""

    # Jobicy reports yearly salaries — convert to hourly.
    if salary_period.lower() == "yearly":
        comp_min = round(salary_min / HOURS_PER_WORK_YEAR, 2) if salary_min else None
        comp_max = round(salary_max / HOURS_PER_WORK_YEAR, 2) if salary_max else None
        comp_period = "hour"
    else:
        comp_min = salary_min or None
        comp_max = salary_max or None
        comp_period = salary_period.lower() if salary_period else "hour"

    # Location
    geo = (raw.get("jobGeo") or "").strip()
    if not geo or geo.lower() in ("worldwide", "global", "anywhere"):
        countries_allowed = ["GLOBAL"]
    else:
        countries_allowed = normalize_countries([geo])

    # Published date
    pub_date_str = raw.get("pubDate")
    published_at = None
    if pub_date_str:
        try:
            dt = datetime.fromisoformat(pub_date_str)
            published_at = dt.astimezone(timezone.utc).isoformat()
        except (ValueError, TypeError):
            pass

    # Industries as categories/skills
    industries = raw.get("jobIndustry") or []
    if isinstance(industries, str):
        industries = [industries]
    categories = [strip_html(i) for i in industries]

    # Job type mapping
    job_types = raw.get("jobType") or []
    if isinstance(job_types, str):
        job_types = [job_types]
    type_lower = " ".join(job_types).lower()
    if "part" in type_lower:
        employment_type = "part_time"
    elif "contract" in type_lower:
        employment_type = "contract"
    elif "temp" in type_lower:
        employment_type = "temporary"
    else:
        employment_type = "part_time"

    return {
        "source_job_id": str(raw.get("id", "")),
        "canonical_url": raw.get("url", ""),
        "title_original": raw.get("jobTitle", ""),
        "title_zh": None,
        "company_name": raw.get("companyName", ""),
        "description_original": sanitize_html(raw.get("jobDescription", "")),
        "description_zh": None,
        "employment_type": employment_type,
        "work_mode": "remote",
        "countries_allowed": countries_allowed,
        "timezone_requirements": [],
        "languages": [],
        "skills": categories,
        "categories": categories,
        "hours_per_week_min": None,
        "hours_per_week_max": None,
        "compensation_min": comp_min,
        "compensation_max": comp_max,
        "compensation_currency": salary_currency,
        "compensation_period": comp_period,
        "published_at": published_at,
        "quality_score": 0.75,
        "extraction_confidence": 0.7,
    }


def fetch(
    *,
    geo: str | None = None,
    industry: str | None = None,
    tag: str | None = None,
    count: int = 50,
    limit: int = 200,
) -> list[dict]:
    """Fetch raw job listings from the Jobicy public API.

    Jobicy caps ``count`` at 100 per request, so we paginate by making
    multiple requests when *limit* exceeds that.  There is no offset
    parameter, so we use the ``tag`` filter to vary results.
    """
    params: dict[str, str | int] = {"count": min(count, 100)}
    if geo:
        params["geo"] = geo
    if industry:
        params["industry"] = industry
    if tag:
        params["tag"] = tag

    url = f"{API_URL}?{urlencode(params)}"
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, context=_SSL_CONTEXT, timeout=30) as response:
        data = json.loads(response.read())

    jobs = data.get("jobs") or []
    return jobs[:limit]
