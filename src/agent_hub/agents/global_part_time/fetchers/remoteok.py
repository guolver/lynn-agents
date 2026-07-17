"""RemoteOK public API fetcher and field mapper.

Pure functions only — no dependency on service, repository, or framework.
Uses stdlib exclusively (urllib, html.parser, json).
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.request import Request, urlopen


class _TagStripper(HTMLParser):
    """Collect text nodes from an HTML fragment."""

    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self._parts.append(data)

    def get_text(self) -> str:
        return " ".join(self._parts)


def strip_html(html: str) -> str:
    """Remove HTML tags and return collapsed plain text."""
    stripper = _TagStripper()
    stripper.feed(html)
    text = stripper.get_text()
    return re.sub(r"\s+", " ", text).strip()


HOURS_PER_WORK_YEAR = 2080


def map_job(raw: dict) -> dict:
    """Convert a single RemoteOK API entry to system JobInput-compatible dict."""
    salary_min = raw.get("salary_min") or 0
    salary_max = raw.get("salary_max") or 0

    location = (raw.get("location") or "").strip()
    if not location or location.lower() in ("worldwide", "global"):
        countries_allowed = ["GLOBAL"]
    else:
        countries_allowed = [location]

    epoch = raw.get("epoch")
    published_at = datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat() if epoch else None

    tags = raw.get("tags") or []

    return {
        "source_job_id": str(raw.get("id", "")),
        "canonical_url": raw.get("url", ""),
        "title_original": raw.get("position", ""),
        "title_zh": None,
        "company_name": raw.get("company", ""),
        "description_original": strip_html(raw.get("description", "")),
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
        "compensation_min": round(salary_min / HOURS_PER_WORK_YEAR, 2) if salary_min else None,
        "compensation_max": round(salary_max / HOURS_PER_WORK_YEAR, 2) if salary_max else None,
        "compensation_currency": "USD",
        "compensation_period": "hour",
        "published_at": published_at,
        "quality_score": 0.7,
        "extraction_confidence": 0.6,
    }


API_URL = "https://remoteok.com/api"
USER_AGENT = "AgentHub/0.2 (+https://github.com/agent-hub)"


def fetch(tags: list[str] | None = None, limit: int = 200) -> list[dict]:
    """Fetch raw job listings from the RemoteOK public API.

    The API returns a JSON array whose first element is metadata — it is
    skipped.  Results are truncated to *limit*.
    """
    url = API_URL
    if tags:
        params = "&".join(f"tag={t}" for t in tags)
        url = f"{url}?{params}"
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request) as response:
        data = json.loads(response.read())
    # First element is always metadata (legal notice, timestamp, etc.)
    jobs = data[1:] if len(data) > 1 else []
    return jobs[:limit]
