# 新增兼职职位来源 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增 3 个免登录、免 API Key 的公开职位来源（Arbeitnow、Working Nomads、We Work Remotely）作为 fetcher 模块接入 Agent Hub 兼职职位管线。

**Architecture:** 每个来源一个独立的纯函数模块（`fetch()` + `map_job()`），放在 `src/agent_hub/agents/global_part_time/fetchers/`，复用现有的 `_SSL_CONTEXT`/`normalize_countries`/`sanitize_html` 工具函数，最后在 `fetchers/__init__.py` 的 `REGISTRY` 里按域名注册。不改动 service/repository/agent 层——来源通过 `service.create_source()` 动态注册，worker 通过 `get_fetcher(base_url)` 按域名自动匹配。

**Tech Stack:** Python 3.10 标准库（`urllib.request`、`json`、`xml.etree.ElementTree`、`email.utils`），`unittest` + `unittest.mock`。

设计文档：`docs/superpowers/specs/2026-07-19-more-part-time-job-sources-design.md`

---

### Task 1: Arbeitnow fetcher

**Files:**
- Create: `src/agent_hub/agents/global_part_time/fetchers/arbeitnow.py`
- Test: `tests/test_arbeitnow_fetcher.py`

- [ ] **Step 1: Write the failing test file**

```python
"""Tests for the Arbeitnow fetcher module."""

import json
import unittest
from unittest.mock import MagicMock, patch

from agent_hub.agents.global_part_time.fetchers.arbeitnow import fetch, map_job
from tests.inmemory_repo import InMemoryRepository as Repository
from agent_hub.agents.global_part_time.service import AgentService


SAMPLE_RAW = {
    "slug": "senior-data-engineer-berlin-391080",
    "company_name": "GLS/NXT",
    "title": "Senior Data Engineer",
    "description": "<p>We are looking for a <strong>Senior</strong> Data Engineer.</p>",
    "remote": True,
    "url": "https://www.arbeitnow.com/jobs/companies/glsnxt/senior-data-engineer-berlin-391080",
    "tags": ["Data Processing", "Data Engineer"],
    "job_types": ["professional / experienced"],
    "location": "Berlin",
    "created_at": 1784457030,
}


class MapJobCompleteTest(unittest.TestCase):
    def setUp(self):
        self.result = map_job(SAMPLE_RAW)

    def test_source_job_id(self):
        self.assertEqual(self.result["source_job_id"], "senior-data-engineer-berlin-391080")

    def test_canonical_url(self):
        self.assertIn("arbeitnow.com", self.result["canonical_url"])

    def test_title(self):
        self.assertEqual(self.result["title_original"], "Senior Data Engineer")

    def test_company(self):
        self.assertEqual(self.result["company_name"], "GLS/NXT")

    def test_description_sanitized(self):
        self.assertEqual(
            self.result["description_original"],
            "<p>We are looking for a <strong>Senior</strong> Data Engineer.</p>",
        )

    def test_skills(self):
        self.assertEqual(self.result["skills"], ["Data Processing", "Data Engineer"])

    def test_categories_same_as_skills(self):
        self.assertEqual(self.result["categories"], ["Data Processing", "Data Engineer"])

    def test_work_mode_remote(self):
        self.assertEqual(self.result["work_mode"], "remote")

    def test_employment_type(self):
        self.assertEqual(self.result["employment_type"], "part_time")

    def test_published_at(self):
        self.assertEqual(self.result["published_at"], "2026-07-19T10:30:30+00:00")

    def test_compensation_is_none(self):
        self.assertIsNone(self.result["compensation_min"])
        self.assertIsNone(self.result["compensation_max"])
        self.assertEqual(self.result["compensation_currency"], "USD")
        self.assertEqual(self.result["compensation_period"], "hour")

    def test_quality_score(self):
        self.assertEqual(self.result["quality_score"], 0.7)

    def test_extraction_confidence(self):
        self.assertEqual(self.result["extraction_confidence"], 0.6)


class MapJobLocationTest(unittest.TestCase):
    def test_empty_location(self):
        raw = {**SAMPLE_RAW, "location": ""}
        self.assertEqual(map_job(raw)["countries_allowed"], ["GLOBAL"])

    def test_country_name(self):
        raw = {**SAMPLE_RAW, "location": "Germany"}
        self.assertEqual(map_job(raw)["countries_allowed"], ["DE"])


PAGE_1 = json.dumps(
    {
        "data": [
            {**SAMPLE_RAW, "slug": "job-1", "remote": True},
            {**SAMPLE_RAW, "slug": "job-2", "remote": False},
            {**SAMPLE_RAW, "slug": "job-3", "remote": True},
        ],
        "links": {"next": "https://www.arbeitnow.com/api/job-board-api?page=2"},
        "meta": {"current_page": 1},
    }
).encode()

PAGE_2 = json.dumps(
    {
        "data": [{**SAMPLE_RAW, "slug": "job-4", "remote": True}],
        "links": {"next": None},
        "meta": {"current_page": 2},
    }
).encode()

EMPTY_PAGE = json.dumps(
    {"data": [], "links": {"next": None}, "meta": {"current_page": 3}}
).encode()


def _mock_urlopen(response_bytes: bytes):
    mock_response = MagicMock()
    mock_response.read.return_value = response_bytes
    mock_response.__enter__ = lambda s: s
    mock_response.__exit__ = MagicMock(return_value=False)
    return mock_response


class FetchTest(unittest.TestCase):
    @patch("agent_hub.agents.global_part_time.fetchers.arbeitnow.urlopen")
    def test_filters_non_remote_jobs(self, mock_urlopen_fn):
        mock_urlopen_fn.side_effect = [_mock_urlopen(PAGE_1), _mock_urlopen(EMPTY_PAGE)]
        jobs = fetch(limit=200)
        self.assertEqual([j["slug"] for j in jobs], ["job-1", "job-3"])

    @patch("agent_hub.agents.global_part_time.fetchers.arbeitnow.urlopen")
    def test_paginates_until_limit_reached(self, mock_urlopen_fn):
        mock_urlopen_fn.side_effect = [_mock_urlopen(PAGE_1), _mock_urlopen(PAGE_2)]
        jobs = fetch(limit=3)
        self.assertEqual(len(jobs), 3)
        self.assertEqual(mock_urlopen_fn.call_count, 2)

    @patch("agent_hub.agents.global_part_time.fetchers.arbeitnow.urlopen")
    def test_stops_at_max_pages(self, mock_urlopen_fn):
        mock_urlopen_fn.return_value = _mock_urlopen(
            json.dumps({"data": [{**SAMPLE_RAW, "remote": False}]}).encode()
        )
        jobs = fetch(limit=200, max_pages=3)
        self.assertEqual(jobs, [])
        self.assertEqual(mock_urlopen_fn.call_count, 3)

    @patch("agent_hub.agents.global_part_time.fetchers.arbeitnow.urlopen")
    def test_stops_on_empty_page(self, mock_urlopen_fn):
        mock_urlopen_fn.side_effect = [_mock_urlopen(EMPTY_PAGE)]
        jobs = fetch(limit=200)
        self.assertEqual(jobs, [])
        self.assertEqual(mock_urlopen_fn.call_count, 1)


ARBEITNOW_SOURCE = {
    "name": "Arbeitnow Public API",
    "source_type": "api",
    "base_url": "https://www.arbeitnow.com/api/job-board-api",
    "authorization_basis": "public API, attribution appreciated",
    "allowed_paths": ["/api"],
    "prohibited_actions": [],
    "rate_limit": "reasonable use",
    "retention_policy": "30 days",
}


class EndToEndSyncTest(unittest.TestCase):
    @patch("agent_hub.agents.global_part_time.fetchers.arbeitnow.urlopen")
    def test_full_pipeline(self, mock_urlopen_fn):
        mock_urlopen_fn.side_effect = [_mock_urlopen(PAGE_1), _mock_urlopen(EMPTY_PAGE)]

        repo = Repository(":memory:")
        service = AgentService(repo)

        source = service.create_source(ARBEITNOW_SOURCE, "operator")
        service.review_source(source["id"], True, "operator")

        raw_jobs = fetch()
        mapped = [map_job(r) for r in raw_jobs]
        result = service.sync_source(source["id"], mapped, "worker")

        self.assertEqual(result["received"], 2)
        self.assertEqual(result["imported"], 2)
        self.assertEqual(result["duplicates"], 0)

        jobs = repo.list("job")
        self.assertEqual(len(jobs), 2)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_arbeitnow_fetcher -v`
Expected: `ModuleNotFoundError: No module named 'agent_hub.agents.global_part_time.fetchers.arbeitnow'`

- [ ] **Step 3: Write the fetcher implementation**

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_arbeitnow_fetcher -v`
Expected: all tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/agent_hub/agents/global_part_time/fetchers/arbeitnow.py tests/test_arbeitnow_fetcher.py
git commit -m "feat: add Arbeitnow job source fetcher"
```

---

### Task 2: Working Nomads fetcher

**Files:**
- Create: `src/agent_hub/agents/global_part_time/fetchers/workingnomads.py`
- Test: `tests/test_workingnomads_fetcher.py`

- [ ] **Step 1: Write the failing test file**

```python
"""Tests for the Working Nomads fetcher module."""

import json
import unittest
from unittest.mock import MagicMock, patch

from agent_hub.agents.global_part_time.fetchers.workingnomads import fetch, map_job
from tests.inmemory_repo import InMemoryRepository as Repository
from agent_hub.agents.global_part_time.service import AgentService


SAMPLE_RAW = {
    "url": "https://www.workingnomads.com/job/go/1734670/",
    "title": "Senior AI Engineer",
    "description": "<p>Are you a talented <strong>Senior AI Engineer</strong>?</p>",
    "company_name": "Lemon.io",
    "category_name": "Development",
    "tags": "python,machine learning,architecture,software engineering,startup",
    "location": "Europe, North America, Latin America, APAC",
    "pub_date": "2026-07-17T07:17:36-04:00",
}


class MapJobCompleteTest(unittest.TestCase):
    def setUp(self):
        self.result = map_job(SAMPLE_RAW)

    def test_source_job_id(self):
        self.assertEqual(
            self.result["source_job_id"], "https://www.workingnomads.com/job/go/1734670/"
        )

    def test_canonical_url(self):
        self.assertEqual(self.result["canonical_url"], SAMPLE_RAW["url"])

    def test_title(self):
        self.assertEqual(self.result["title_original"], "Senior AI Engineer")

    def test_company(self):
        self.assertEqual(self.result["company_name"], "Lemon.io")

    def test_description_sanitized(self):
        self.assertEqual(
            self.result["description_original"],
            "<p>Are you a talented <strong>Senior AI Engineer</strong>?</p>",
        )

    def test_skills_split_from_comma_string(self):
        self.assertEqual(
            self.result["skills"],
            ["python", "machine learning", "architecture", "software engineering", "startup"],
        )

    def test_categories(self):
        self.assertEqual(self.result["categories"], ["Development"])

    def test_countries_allowed_covers_regions(self):
        countries = self.result["countries_allowed"]
        self.assertIn("GB", countries)  # Europe
        self.assertIn("US", countries)  # North America
        self.assertIn("BR", countries)  # Latin America
        self.assertIn("CN", countries)  # APAC

    def test_work_mode_remote(self):
        self.assertEqual(self.result["work_mode"], "remote")

    def test_employment_type(self):
        self.assertEqual(self.result["employment_type"], "part_time")

    def test_published_at(self):
        self.assertEqual(self.result["published_at"], "2026-07-17T07:17:36-04:00")

    def test_compensation_is_none(self):
        self.assertIsNone(self.result["compensation_min"])
        self.assertIsNone(self.result["compensation_max"])
        self.assertEqual(self.result["compensation_currency"], "USD")
        self.assertEqual(self.result["compensation_period"], "hour")

    def test_quality_score(self):
        self.assertEqual(self.result["quality_score"], 0.7)

    def test_extraction_confidence(self):
        self.assertEqual(self.result["extraction_confidence"], 0.6)


class MapJobLocationTest(unittest.TestCase):
    def test_empty_location(self):
        raw = {**SAMPLE_RAW, "location": ""}
        self.assertEqual(map_job(raw)["countries_allowed"], ["GLOBAL"])

    def test_single_region(self):
        raw = {**SAMPLE_RAW, "location": "Europe"}
        countries = map_job(raw)["countries_allowed"]
        self.assertIn("DE", countries)
        self.assertIn("FR", countries)


MOCK_API_RESPONSE = json.dumps(
    [
        {**SAMPLE_RAW, "url": "https://www.workingnomads.com/job/go/1/"},
        {**SAMPLE_RAW, "url": "https://www.workingnomads.com/job/go/2/"},
    ]
).encode()


def _mock_urlopen(response_bytes: bytes):
    mock_response = MagicMock()
    mock_response.read.return_value = response_bytes
    mock_response.__enter__ = lambda s: s
    mock_response.__exit__ = MagicMock(return_value=False)
    return mock_response


class FetchTest(unittest.TestCase):
    @patch("agent_hub.agents.global_part_time.fetchers.workingnomads.urlopen")
    def test_returns_jobs_array(self, mock_urlopen_fn):
        mock_urlopen_fn.return_value = _mock_urlopen(MOCK_API_RESPONSE)
        jobs = fetch()
        self.assertEqual(len(jobs), 2)
        self.assertEqual(jobs[0]["url"], "https://www.workingnomads.com/job/go/1/")

    @patch("agent_hub.agents.global_part_time.fetchers.workingnomads.urlopen")
    def test_limit_truncates(self, mock_urlopen_fn):
        mock_urlopen_fn.return_value = _mock_urlopen(MOCK_API_RESPONSE)
        jobs = fetch(limit=1)
        self.assertEqual(len(jobs), 1)


WORKINGNOMADS_SOURCE = {
    "name": "Working Nomads Public API",
    "source_type": "api",
    "base_url": "https://www.workingnomads.com/api/exposed_jobs/",
    "authorization_basis": "public API, no key required",
    "allowed_paths": ["/api"],
    "prohibited_actions": [],
    "rate_limit": "reasonable use",
    "retention_policy": "30 days",
}


class EndToEndSyncTest(unittest.TestCase):
    @patch("agent_hub.agents.global_part_time.fetchers.workingnomads.urlopen")
    def test_full_pipeline(self, mock_urlopen_fn):
        mock_urlopen_fn.return_value = _mock_urlopen(MOCK_API_RESPONSE)

        repo = Repository(":memory:")
        service = AgentService(repo)

        source = service.create_source(WORKINGNOMADS_SOURCE, "operator")
        service.review_source(source["id"], True, "operator")

        raw_jobs = fetch()
        mapped = [map_job(r) for r in raw_jobs]
        result = service.sync_source(source["id"], mapped, "worker")

        self.assertEqual(result["received"], 2)
        self.assertEqual(result["imported"], 2)
        self.assertEqual(result["duplicates"], 0)

        jobs = repo.list("job")
        self.assertEqual(len(jobs), 2)

        mock_urlopen_fn.return_value = _mock_urlopen(MOCK_API_RESPONSE)
        result2 = service.sync_source(source["id"], [map_job(r) for r in fetch()], "worker")
        self.assertEqual(result2["imported"], 0)
        self.assertEqual(result2["duplicates"], 2)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_workingnomads_fetcher -v`
Expected: `ModuleNotFoundError: No module named 'agent_hub.agents.global_part_time.fetchers.workingnomads'`

- [ ] **Step 3: Write the fetcher implementation**

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_workingnomads_fetcher -v`
Expected: all tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/agent_hub/agents/global_part_time/fetchers/workingnomads.py tests/test_workingnomads_fetcher.py
git commit -m "feat: add Working Nomads job source fetcher"
```

---

### Task 3: We Work Remotely fetcher (RSS)

**Files:**
- Create: `src/agent_hub/agents/global_part_time/fetchers/weworkremotely.py`
- Test: `tests/test_weworkremotely_fetcher.py`

- [ ] **Step 1: Write the failing test file**

```python
"""Tests for the We Work Remotely RSS fetcher module."""

import unittest
from unittest.mock import MagicMock, patch

from agent_hub.agents.global_part_time.fetchers.weworkremotely import fetch, map_job
from tests.inmemory_repo import InMemoryRepository as Repository
from agent_hub.agents.global_part_time.service import AgentService


SAMPLE_RAW = {
    "title": "LawnStarter: Data Governance & Platform Manager",
    "region": "Anywhere in the World",
    "category": "All Other Remote",
    "type": "Full-Time",
    "description": "<p>We are hiring a <strong>Data Governance Manager</strong>.</p>",
    "pubDate": "Fri, 17 Jul 2026 20:07:06 +0000",
    "guid": "https://weworkremotely.com/remote-jobs/lawnstarter-data-governance-platform-manager",
    "link": "https://weworkremotely.com/remote-jobs/lawnstarter-data-governance-platform-manager",
}


class MapJobCompleteTest(unittest.TestCase):
    def setUp(self):
        self.result = map_job(SAMPLE_RAW)

    def test_source_job_id(self):
        self.assertEqual(self.result["source_job_id"], SAMPLE_RAW["guid"])

    def test_canonical_url(self):
        self.assertEqual(self.result["canonical_url"], SAMPLE_RAW["link"])

    def test_title_split_from_company(self):
        self.assertEqual(self.result["title_original"], "Data Governance & Platform Manager")

    def test_company_split_from_title(self):
        self.assertEqual(self.result["company_name"], "LawnStarter")

    def test_description_sanitized(self):
        self.assertEqual(
            self.result["description_original"],
            "<p>We are hiring a <strong>Data Governance Manager</strong>.</p>",
        )

    def test_categories(self):
        self.assertEqual(self.result["categories"], ["All Other Remote"])

    def test_countries_allowed_global(self):
        self.assertEqual(self.result["countries_allowed"], ["GLOBAL"])

    def test_work_mode_remote(self):
        self.assertEqual(self.result["work_mode"], "remote")

    def test_employment_type_full_time_defaults_part_time(self):
        self.assertEqual(self.result["employment_type"], "part_time")

    def test_employment_type_contract(self):
        raw = {**SAMPLE_RAW, "type": "Contract"}
        self.assertEqual(map_job(raw)["employment_type"], "contract")

    def test_published_at(self):
        self.assertEqual(self.result["published_at"], "2026-07-17T20:07:06+00:00")

    def test_compensation_is_none(self):
        self.assertIsNone(self.result["compensation_min"])
        self.assertIsNone(self.result["compensation_max"])
        self.assertEqual(self.result["compensation_currency"], "USD")
        self.assertEqual(self.result["compensation_period"], "hour")

    def test_quality_score(self):
        self.assertEqual(self.result["quality_score"], 0.7)

    def test_extraction_confidence(self):
        self.assertEqual(self.result["extraction_confidence"], 0.6)


class MapJobTitleFallbackTest(unittest.TestCase):
    def test_no_colon_in_title(self):
        raw = {**SAMPLE_RAW, "title": "Data Governance Manager"}
        result = map_job(raw)
        self.assertEqual(result["title_original"], "Data Governance Manager")
        self.assertEqual(result["company_name"], "")


class MapJobLocationTest(unittest.TestCase):
    def test_us_state_region(self):
        raw = {**SAMPLE_RAW, "region": "California"}
        self.assertEqual(map_job(raw)["countries_allowed"], ["US"])

    def test_empty_region(self):
        raw = {**SAMPLE_RAW, "region": ""}
        self.assertEqual(map_job(raw)["countries_allowed"], ["GLOBAL"])


RSS_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:media="http://search.yahoo.com/mrss">
  <channel>
    <title>We Work Remotely</title>
    <item>
      <title>LawnStarter: Data Governance &amp; Platform Manager</title>
      <region>Anywhere in the World</region>
      <category>All Other Remote</category>
      <type>Full-Time</type>
      <description>&lt;p&gt;We are hiring.&lt;/p&gt;</description>
      <pubDate>Fri, 17 Jul 2026 20:07:06 +0000</pubDate>
      <guid>https://weworkremotely.com/remote-jobs/lawnstarter-data-governance-platform-manager</guid>
      <link>https://weworkremotely.com/remote-jobs/lawnstarter-data-governance-platform-manager</link>
    </item>
    <item>
      <title>Acme Inc: Backend Engineer</title>
      <region>USA Only</region>
      <category>Programming</category>
      <type>Contract</type>
      <description>&lt;p&gt;Build things.&lt;/p&gt;</description>
      <pubDate>Thu, 16 Jul 2026 12:00:00 +0000</pubDate>
      <guid>https://weworkremotely.com/remote-jobs/acme-backend-engineer</guid>
      <link>https://weworkremotely.com/remote-jobs/acme-backend-engineer</link>
    </item>
  </channel>
</rss>
""".encode()


def _mock_urlopen(response_bytes: bytes):
    mock_response = MagicMock()
    mock_response.read.return_value = response_bytes
    mock_response.__enter__ = lambda s: s
    mock_response.__exit__ = MagicMock(return_value=False)
    return mock_response


class FetchTest(unittest.TestCase):
    @patch("agent_hub.agents.global_part_time.fetchers.weworkremotely.urlopen")
    def test_parses_rss_items(self, mock_urlopen_fn):
        mock_urlopen_fn.return_value = _mock_urlopen(RSS_FEED)
        jobs = fetch()
        self.assertEqual(len(jobs), 2)
        self.assertEqual(jobs[0]["title"], "LawnStarter: Data Governance & Platform Manager")
        self.assertEqual(jobs[1]["type"], "Contract")

    @patch("agent_hub.agents.global_part_time.fetchers.weworkremotely.urlopen")
    def test_limit_truncates(self, mock_urlopen_fn):
        mock_urlopen_fn.return_value = _mock_urlopen(RSS_FEED)
        jobs = fetch(limit=1)
        self.assertEqual(len(jobs), 1)


WWR_SOURCE = {
    "name": "We Work Remotely RSS",
    "source_type": "rss",
    "base_url": "https://weworkremotely.com/remote-jobs.rss",
    "authorization_basis": "public RSS feed",
    "allowed_paths": ["/remote-jobs.rss"],
    "prohibited_actions": [],
    "rate_limit": "reasonable use",
    "retention_policy": "30 days",
}


class EndToEndSyncTest(unittest.TestCase):
    @patch("agent_hub.agents.global_part_time.fetchers.weworkremotely.urlopen")
    def test_full_pipeline(self, mock_urlopen_fn):
        mock_urlopen_fn.return_value = _mock_urlopen(RSS_FEED)

        repo = Repository(":memory:")
        service = AgentService(repo)

        source = service.create_source(WWR_SOURCE, "operator")
        service.review_source(source["id"], True, "operator")

        raw_jobs = fetch()
        mapped = [map_job(r) for r in raw_jobs]
        result = service.sync_source(source["id"], mapped, "worker")

        self.assertEqual(result["received"], 2)
        self.assertEqual(result["imported"], 2)
        self.assertEqual(result["duplicates"], 0)

        jobs = repo.list("job")
        self.assertEqual(len(jobs), 2)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_weworkremotely_fetcher -v`
Expected: `ModuleNotFoundError: No module named 'agent_hub.agents.global_part_time.fetchers.weworkremotely'`

- [ ] **Step 3: Write the fetcher implementation**

```python
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
        {tag: (item.findtext(tag) or "") for tag in _ITEM_TAGS}
        for item in root.findall(".//item")
    ]
    return items[:limit]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_weworkremotely_fetcher -v`
Expected: all tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/agent_hub/agents/global_part_time/fetchers/weworkremotely.py tests/test_weworkremotely_fetcher.py
git commit -m "feat: add We Work Remotely RSS job source fetcher"
```

---

### Task 4: Register all 3 fetchers in the domain registry

**Files:**
- Modify: `src/agent_hub/agents/global_part_time/fetchers/__init__.py:434-451`
- Test: `tests/test_fetchers_registry.py`

- [ ] **Step 1: Write the failing test file**

```python
"""Tests for the fetcher domain registry."""

import unittest

from agent_hub.agents.global_part_time.fetchers import get_fetcher
from agent_hub.agents.global_part_time.fetchers.arbeitnow import fetch as arbeitnow_fetch
from agent_hub.agents.global_part_time.fetchers.arbeitnow import map_job as arbeitnow_map
from agent_hub.agents.global_part_time.fetchers.weworkremotely import (
    fetch as weworkremotely_fetch,
)
from agent_hub.agents.global_part_time.fetchers.weworkremotely import map_job as weworkremotely_map
from agent_hub.agents.global_part_time.fetchers.workingnomads import fetch as workingnomads_fetch
from agent_hub.agents.global_part_time.fetchers.workingnomads import map_job as workingnomads_map


class GetFetcherNewSourcesTest(unittest.TestCase):
    def test_arbeitnow_resolves(self):
        funcs = get_fetcher("https://www.arbeitnow.com/api/job-board-api")
        self.assertEqual(funcs, (arbeitnow_fetch, arbeitnow_map))

    def test_workingnomads_resolves(self):
        funcs = get_fetcher("https://www.workingnomads.com/api/exposed_jobs/")
        self.assertEqual(funcs, (workingnomads_fetch, workingnomads_map))

    def test_weworkremotely_resolves(self):
        funcs = get_fetcher("https://weworkremotely.com/remote-jobs.rss")
        self.assertEqual(funcs, (weworkremotely_fetch, weworkremotely_map))

    def test_unknown_domain_returns_none(self):
        self.assertIsNone(get_fetcher("https://example.com/jobs"))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_fetchers_registry -v`
Expected: FAIL — `test_arbeitnow_resolves`, `test_workingnomads_resolves`, `test_weworkremotely_resolves` fail because `get_fetcher()` returns `None` for the new domains (they aren't in `REGISTRY` yet)

- [ ] **Step 3: Register the new domains**

In `src/agent_hub/agents/global_part_time/fetchers/__init__.py`, replace the `get_fetcher` function body (currently lines 434-451):

```python
def get_fetcher(base_url: str) -> tuple[Callable, Callable] | None:
    """Return ``(fetch_fn, map_job_fn)`` for *base_url*, or ``None`` if unrecognised."""
    from .arbeitnow import fetch as arbeitnow_fetch, map_job as arbeitnow_map
    from .himalayas import fetch as himalayas_fetch, map_job as himalayas_map
    from .jobicy import fetch as jobicy_fetch, map_job as jobicy_map
    from .remoteok import fetch as remoteok_fetch, map_job as remoteok_map
    from .remotive import fetch as remotive_fetch, map_job as remotive_map
    from .weworkremotely import fetch as weworkremotely_fetch, map_job as weworkremotely_map
    from .workingnomads import fetch as workingnomads_fetch, map_job as workingnomads_map

    _REGISTRY: dict[str, tuple[Callable, Callable]] = {
        "remoteok.com": (remoteok_fetch, remoteok_map),
        "remotive.com": (remotive_fetch, remotive_map),
        "jobicy.com": (jobicy_fetch, jobicy_map),
        "himalayas.app": (himalayas_fetch, himalayas_map),
        "arbeitnow.com": (arbeitnow_fetch, arbeitnow_map),
        "workingnomads.com": (workingnomads_fetch, workingnomads_map),
        "weworkremotely.com": (weworkremotely_fetch, weworkremotely_map),
    }
    for domain, funcs in _REGISTRY.items():
        if domain in base_url:
            return funcs
    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_fetchers_registry -v`
Expected: all tests PASS

Then run the full suite to confirm no regressions:

Run: `python -m unittest discover -s tests -v`
Expected: all tests PASS (existing + 4 new test files)

- [ ] **Step 5: Commit**

```bash
git add src/agent_hub/agents/global_part_time/fetchers/__init__.py tests/test_fetchers_registry.py
git commit -m "feat: register Arbeitnow, Working Nomads, We Work Remotely in fetcher registry"
```

---

### Task 5: Lint check

**Files:** none (verification only)

- [ ] **Step 1: Run ruff**

Run: `ruff check src/agent_hub/agents/global_part_time/fetchers/ tests/test_arbeitnow_fetcher.py tests/test_workingnomads_fetcher.py tests/test_weworkremotely_fetcher.py tests/test_fetchers_registry.py`
Expected: no errors. If ruff flags formatting issues, run `ruff format` on the same paths and re-run `ruff check`.

- [ ] **Step 2: Commit (only if ruff format changed anything)**

```bash
git add -u
git commit -m "style: ruff format new fetcher files"
```

---

## Notes for the implementer

- All three upstream endpoints were verified live (via `curl`) while writing this plan on 2026-07-19, so the sample fixtures reflect real response shapes. If an endpoint's schema has since changed, update the fixture and mapping together — don't guess.
- Arbeitnow's `?remote=true` query parameter does **not** filter server-side (confirmed empirically) — this is why `fetch()` must filter client-side. Do not "simplify" this away by trusting the query parameter.
- `datetime.fromisoformat` (Working Nomads) works with the `-04:00`-style offset used here under Python 3.10, but does **not** accept a trailing `Z`. This project's fixtures never produce `Z`, so no extra handling is needed.
- Do not add a `FetcherProtocol` abstraction or a shared base class for these 3 fetchers — the existing 4 fetchers already tolerate this duplication (see design doc "不做的事情"), and introducing an abstraction here would be inconsistent with the rest of the package.
