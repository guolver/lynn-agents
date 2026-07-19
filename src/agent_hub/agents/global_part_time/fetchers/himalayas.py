"""Himalayas public API fetcher and field mapper.

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

API_URL = "https://himalayas.app/jobs/api"
USER_AGENT = "AgentHub/0.2 (+https://github.com/agent-hub)"


def map_job(raw: dict) -> dict:
    """Convert a single Himalayas API entry to system JobInput-compatible dict."""
    salary_min = raw.get("minSalary") or 0
    salary_max = raw.get("maxSalary") or 0
    salary_currency = raw.get("currency") or "USD"
    salary_period = raw.get("salaryPeriod") or "annual"

    # Himalayas reports annual salaries — convert to hourly.
    if salary_period.lower() in ("annual", "yearly"):
        comp_min = round(salary_min / HOURS_PER_WORK_YEAR, 2) if salary_min else None
        comp_max = round(salary_max / HOURS_PER_WORK_YEAR, 2) if salary_max else None
        comp_period = "hour"
    else:
        comp_min = salary_min or None
        comp_max = salary_max or None
        comp_period = salary_period.lower()

    # Location
    locations = raw.get("locationRestrictions") or []
    if not locations:
        countries_allowed = ["GLOBAL"]
    else:
        countries_allowed = normalize_countries([str(loc) for loc in locations])

    # Timezone requirements
    tz_restrictions = raw.get("timezoneRestrictions") or []
    tz_requirements = [f"UTC{tz:+d}" if isinstance(tz, int) else str(tz) for tz in tz_restrictions]

    # Published date (epoch seconds)
    pub_date = raw.get("pubDate")
    published_at = None
    if pub_date and isinstance(pub_date, (int, float)):
        published_at = datetime.fromtimestamp(pub_date, tz=timezone.utc).isoformat()

    # Categories
    categories = raw.get("categories") or []
    parent_categories = raw.get("parentCategories") or []
    # Clean up category slugs: "Software-Engineering" → "Software Engineering"
    skills = [c.replace("-", " ") for c in categories[:10]]
    cat_list = [c.replace("-", " ") for c in parent_categories] or skills[:5]

    # Employment type
    emp_type = (raw.get("employmentType") or "").lower()
    if "part" in emp_type:
        employment_type = "part_time"
    elif "contract" in emp_type:
        employment_type = "contract"
    elif "temp" in emp_type or "intern" in emp_type:
        employment_type = "temporary"
    else:
        employment_type = "part_time"

    return {
        "source_job_id": raw.get("guid") or raw.get("applicationLink") or "",
        "canonical_url": raw.get("applicationLink") or raw.get("guid") or "",
        "title_original": raw.get("title", ""),
        "title_zh": None,
        "company_name": raw.get("companyName", ""),
        "description_original": sanitize_html(raw.get("description", "")),
        "description_zh": None,
        "employment_type": employment_type,
        "work_mode": "remote",
        "countries_allowed": countries_allowed,
        "timezone_requirements": tz_requirements,
        "languages": [],
        "skills": skills,
        "categories": cat_list,
        "hours_per_week_min": None,
        "hours_per_week_max": None,
        "compensation_min": comp_min,
        "compensation_max": comp_max,
        "compensation_currency": salary_currency,
        "compensation_period": comp_period,
        "published_at": published_at,
        "quality_score": 0.8,
        "extraction_confidence": 0.75,
    }


def fetch(*, limit: int = 200, start_offset: int = 0) -> list[dict]:
    """Fetch raw job listings from the Himalayas public API.

    Himalayas caps ``limit`` at 20 per request, so we paginate via
    ``offset`` until we reach the desired *limit*.  If a single page
    times out we return whatever we collected so far.
    """
    import time

    all_jobs: list[dict] = []
    page_size = 20  # Himalayas max per request
    offset = start_offset
    retries = 0
    max_retries = 2

    while len(all_jobs) < limit:
        remaining = limit - len(all_jobs)
        batch = min(page_size, remaining)
        params = {"limit": batch, "offset": offset}
        url = f"{API_URL}?{urlencode(params)}"
        request = Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urlopen(request, context=_SSL_CONTEXT, timeout=60) as response:
                data = json.loads(response.read())
        except (TimeoutError, OSError):
            retries += 1
            if retries > max_retries:
                break  # return what we have
            time.sleep(2)
            continue

        jobs = data.get("jobs") or []
        if not jobs:
            break
        all_jobs.extend(jobs)
        offset += len(jobs)
        retries = 0  # reset on success

    return all_jobs[:limit]
