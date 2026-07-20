"""We Work Remotely RSS fetcher and field mapper.

Pure functions only — no dependency on service, repository, or framework.
Unlike the JSON-based fetchers in this package, the source feed is RSS/XML;
``fetch()`` still returns ``list[dict]`` to keep the same interface contract.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from urllib.request import Request, urlopen

from . import _SSL_CONTEXT, normalize_countries, sanitize_html

__all__ = ["fetch", "map_job"]

RSS_URL = "https://weworkremotely.com/remote-jobs.rss"
USER_AGENT = "AgentHub/0.2 (+https://github.com/agent-hub)"

_ITEM_TAGS = ("title", "region", "category", "type", "description", "pubDate", "guid", "link")


def map_job(raw: dict) -> dict:
    """Convert a single We Work Remotely RSS item to system JobInput-compatible dict."""
    title = raw.get("title") or ""
    if ": " in title:
        company_name, title_original = title.split(": ", 1)
    else:
        company_name, title_original = "", title

    region = (raw.get("region") or "").strip()
    countries_allowed = normalize_countries([region]) if region else ["GLOBAL"]

    category = raw.get("category") or ""

    job_type = (raw.get("type") or "").lower()
    employment_type = "contract" if "contract" in job_type else "part_time"

    pub_date = raw.get("pubDate")
    published_at = None
    if pub_date:
        try:
            published_at = parsedate_to_datetime(pub_date).isoformat()
        except (TypeError, ValueError):
            pass

    canonical_url = raw.get("link") or raw.get("guid") or ""

    return {
        "source_job_id": raw.get("guid") or canonical_url,
        "canonical_url": canonical_url,
        "title_original": title_original.strip(),
        "title_zh": None,
        "company_name": company_name.strip(),
        "description_original": sanitize_html(raw.get("description", "")),
        "description_zh": None,
        "employment_type": employment_type,
        "work_mode": "remote",
        "countries_allowed": countries_allowed,
        "timezone_requirements": [],
        "languages": [],
        "skills": [],
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
    """Fetch raw job listings from the We Work Remotely RSS feed.

    Parses ``<item>`` elements into plain dicts keyed by tag name so the
    interface matches the JSON-based fetchers in this package.
    """
    request = Request(RSS_URL, headers={"User-Agent": USER_AGENT})
    with urlopen(request, context=_SSL_CONTEXT, timeout=30) as response:
        root = ET.fromstring(response.read())
    items = [
        {tag: (item.findtext(tag) or "") for tag in _ITEM_TAGS} for item in root.findall(".//item")
    ]
    return items[:limit]
