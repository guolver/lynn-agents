"""Working Nomads public API fetcher and field mapper.

Pure functions only — no dependency on service, repository, or framework.
"""

from __future__ import annotations

import json
from datetime import datetime
from urllib.request import Request, urlopen

from . import _SSL_CONTEXT, normalize_countries, sanitize_html

__all__ = ["fetch", "map_job"]

API_URL = "https://www.workingnomads.com/api/exposed_jobs/"
USER_AGENT = "AgentHub/0.2 (+https://github.com/agent-hub)"


def map_job(raw: dict) -> dict:
    """Convert a single Working Nomads API entry to system JobInput-compatible dict."""
    location = raw.get("location") or ""
    locations = [part.strip() for part in location.split(",") if part.strip()]
    countries_allowed = normalize_countries(locations) if locations else ["GLOBAL"]

    pub_date = raw.get("pub_date")
    published_at = None
    if pub_date:
        try:
            published_at = datetime.fromisoformat(pub_date).isoformat()
        except ValueError:
            pass

    tags_raw = raw.get("tags") or ""
    skills = [tag.strip() for tag in tags_raw.split(",") if tag.strip()]

    category = raw.get("category_name") or ""

    return {
        "source_job_id": raw.get("url", ""),
        "canonical_url": raw.get("url", ""),
        "title_original": raw.get("title", ""),
        "title_zh": None,
        "company_name": raw.get("company_name", ""),
        "description_original": sanitize_html(raw.get("description", "")),
        "description_zh": None,
        "employment_type": "part_time",
        "work_mode": "remote",
        "countries_allowed": countries_allowed,
        "timezone_requirements": [],
        "languages": [],
        "skills": skills,
        "categories": [category] if category else [],
        "hours_per_week_min": None,
        "hours_per_week_max": None,
        "compensation_min": None,
        "compensation_max": None,
        "compensation_currency": "USD",
        "compensation_period": "hour",
        "published_at": published_at,
        "quality_score": 0.7,
        "extraction_confidence": 0.6,
    }


def fetch(limit: int = 200) -> list[dict]:
    """Fetch raw job listings from the Working Nomads public API.

    The API returns the full job list in a single response (no pagination
    parameters) — truncate to *limit* client-side.
    """
    request = Request(API_URL, headers={"User-Agent": USER_AGENT})
    with urlopen(request, context=_SSL_CONTEXT, timeout=30) as response:
        data = json.loads(response.read())
    return data[:limit]
