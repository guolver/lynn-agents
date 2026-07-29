"""Arbeitnow public API fetcher and field mapper.

Pure functions only — no dependency on service, repository, or framework.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from urllib.request import Request, urlopen

from . import _SSL_CONTEXT, normalize_countries, sanitize_html

__all__ = ["fetch", "map_job"]

API_URL = "https://www.arbeitnow.com/api/job-board-api"
USER_AGENT = "AgentHub/0.2 (+https://github.com/agent-hub)"


def map_job(raw: dict) -> dict:
    """Convert a single Arbeitnow API entry to system JobInput-compatible dict."""
    location = (raw.get("location") or "").strip()
    countries_allowed = normalize_countries([location]) if location else ["GLOBAL"]

    created_at = raw.get("created_at")
    published_at = (
        datetime.fromtimestamp(created_at, tz=timezone.utc).isoformat() if created_at else None
    )

    tags = raw.get("tags") or []

    return {
        "source_job_id": raw.get("slug", ""),
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
        "skills": list(tags),
        "categories": list(tags),
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


def fetch(limit: int = 200, max_pages: int = 10) -> list[dict]:
    """Fetch raw remote job listings from the Arbeitnow public API.

    Arbeitnow mixes remote and on-site jobs and its ``remote`` query
    parameter is not honored server-side, so we filter client-side while
    paginating via ``?page=N`` until *limit* remote jobs are collected, a
    page returns no data, or *max_pages* is exceeded (safety cap against
    runaway pagination).
    """
    remote_jobs: list[dict] = []
    page = 1
    while len(remote_jobs) < limit and page <= max_pages:
        url = f"{API_URL}?page={page}"
        request = Request(url, headers={"User-Agent": USER_AGENT})
        with urlopen(request, context=_SSL_CONTEXT, timeout=30) as response:
            data = json.loads(response.read())
        page_jobs = data.get("data") or []
        if not page_jobs:
            break
        remote_jobs.extend(job for job in page_jobs if job.get("remote") is True)
        page += 1
    return remote_jobs[:limit]
