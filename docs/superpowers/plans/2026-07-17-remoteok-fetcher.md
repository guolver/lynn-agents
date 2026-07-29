# RemoteOK Fetcher Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Integrate RemoteOK public API as the first real job source, running the full pipeline from source registration through data fetch, field mapping, and sync into the existing job store.

**Architecture:** A pure-function fetcher module inside the global-part-time agent fetches raw JSON from RemoteOK's public API and maps each entry to the system's `JobInput`-compatible dict. A CLI script orchestrates the full flow: register source → approve → fetch → map → sync_source. All risk assessment, deduplication, and storage are handled by the existing `AgentService.sync_source`.

**Tech Stack:** Python 3.10+, stdlib only (`urllib.request`, `html.parser`, `json`, `argparse`). No new dependencies.

**Spec:** `docs/superpowers/specs/2026-07-17-remoteok-fetcher-design.md`

---

## File Structure

| File | Responsibility |
|------|---------------|
| `agent_hub/agents/global_part_time/fetchers/__init__.py` | Package marker (empty) |
| `agent_hub/agents/global_part_time/fetchers/remoteok.py` | `strip_html()`, `map_job()`, `fetch()` — pure functions for data retrieval and transformation |
| `scripts/sync_remoteok.py` | CLI entry point: register source → approve → fetch → map → sync |
| `tests/test_remoteok_fetcher.py` | Unit tests for strip_html, map_job, fetch, and end-to-end sync |

---

### Task 1: strip_html — HTML tag removal utility

**Files:**
- Create: `tests/test_remoteok_fetcher.py`
- Create: `agent_hub/agents/global_part_time/fetchers/__init__.py`
- Create: `agent_hub/agents/global_part_time/fetchers/remoteok.py`

- [ ] **Step 1: Write the failing tests for strip_html**

Create `tests/test_remoteok_fetcher.py`:

```python
"""Tests for the RemoteOK fetcher module."""

import unittest

from agent_hub.agents.global_part_time.fetchers.remoteok import strip_html


class StripHtmlTest(unittest.TestCase):
    def test_removes_tags(self):
        self.assertEqual(strip_html("<p>Hello <b>world</b></p>"), "Hello world")

    def test_preserves_plain_text(self):
        self.assertEqual(strip_html("no tags here"), "no tags here")

    def test_empty_string(self):
        self.assertEqual(strip_html(""), "")

    def test_nested_tags(self):
        self.assertEqual(
            strip_html("<div><ul><li>item</li></ul></div>"), "item"
        )

    def test_br_adds_space(self):
        result = strip_html("line1<br>line2<br/>line3")
        self.assertIn("line1", result)
        self.assertIn("line2", result)

    def test_strips_whitespace(self):
        result = strip_html("  <p>  spaced  </p>  ")
        self.assertEqual(result, "spaced")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_remoteok_fetcher.py -v`
Expected: FAIL — `ModuleNotFoundError` or `ImportError`

- [ ] **Step 3: Create package and implement strip_html**

Create `agent_hub/agents/global_part_time/fetchers/__init__.py` (empty file).

Create `agent_hub/agents/global_part_time/fetchers/remoteok.py`:

```python
"""RemoteOK public API fetcher and field mapper.

Pure functions only — no dependency on service, repository, or framework.
Uses stdlib exclusively (urllib, html.parser, json).
"""

from __future__ import annotations

import re
from html.parser import HTMLParser


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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_remoteok_fetcher.py::StripHtmlTest -v`
Expected: All 6 tests PASS

- [ ] **Step 5: Commit**

```bash
git add agent_hub/agents/global_part_time/fetchers/__init__.py \
        agent_hub/agents/global_part_time/fetchers/remoteok.py \
        tests/test_remoteok_fetcher.py
git commit -m "feat: add strip_html utility for RemoteOK fetcher"
```

---

### Task 2: map_job — field mapping from RemoteOK to system schema

**Files:**
- Modify: `tests/test_remoteok_fetcher.py`
- Modify: `agent_hub/agents/global_part_time/fetchers/remoteok.py`

- [ ] **Step 1: Write the failing tests for map_job**

Append to `tests/test_remoteok_fetcher.py`:

```python
from agent_hub.agents.global_part_time.fetchers.remoteok import map_job


SAMPLE_RAW = {
    "id": "1134957",
    "slug": "remote-python-developer",
    "company": "Acme Corp",
    "position": "Python Developer",
    "description": "<p>Build <b>APIs</b> for our platform.</p>",
    "location": "Worldwide",
    "tags": ["python", "api", "backend"],
    "salary_min": 60000,
    "salary_max": 120000,
    "url": "https://remoteok.com/remote-jobs/1134957",
    "apply_url": "https://acme.com/apply",
    "epoch": 1752700800,
    "original": True,
    "company_logo": "",
    "logo": "",
}


class MapJobCompleteTest(unittest.TestCase):
    def setUp(self):
        self.result = map_job(SAMPLE_RAW)

    def test_source_job_id(self):
        self.assertEqual(self.result["source_job_id"], "1134957")

    def test_canonical_url(self):
        self.assertEqual(
            self.result["canonical_url"],
            "https://remoteok.com/remote-jobs/1134957",
        )

    def test_title(self):
        self.assertEqual(self.result["title_original"], "Python Developer")

    def test_company(self):
        self.assertEqual(self.result["company_name"], "Acme Corp")

    def test_description_stripped(self):
        self.assertEqual(
            self.result["description_original"], "Build APIs for our platform."
        )

    def test_skills(self):
        self.assertEqual(self.result["skills"], ["python", "api", "backend"])

    def test_categories(self):
        self.assertEqual(self.result["categories"], ["python", "api", "backend"])

    def test_worldwide_location(self):
        self.assertEqual(self.result["countries_allowed"], ["GLOBAL"])

    def test_work_mode_remote(self):
        self.assertEqual(self.result["work_mode"], "remote")

    def test_salary_converted_to_hourly(self):
        # 60000 / 2080 ≈ 28.85, 120000 / 2080 ≈ 57.69
        self.assertAlmostEqual(self.result["compensation_min"], 28.85, places=2)
        self.assertAlmostEqual(self.result["compensation_max"], 57.69, places=2)

    def test_compensation_currency_and_period(self):
        self.assertEqual(self.result["compensation_currency"], "USD")
        self.assertEqual(self.result["compensation_period"], "hour")

    def test_employment_type(self):
        self.assertEqual(self.result["employment_type"], "part_time")

    def test_extraction_confidence(self):
        self.assertEqual(self.result["extraction_confidence"], 0.6)

    def test_quality_score(self):
        self.assertEqual(self.result["quality_score"], 0.7)

    def test_languages_empty(self):
        self.assertEqual(self.result["languages"], [])

    def test_hours_per_week_none(self):
        self.assertIsNone(self.result["hours_per_week_min"])
        self.assertIsNone(self.result["hours_per_week_max"])

    def test_published_at_iso(self):
        self.assertIn("2026-07-16", self.result["published_at"])


class MapJobSalaryEdgeCasesTest(unittest.TestCase):
    def test_salary_zero_becomes_none(self):
        raw = {**SAMPLE_RAW, "salary_min": 0, "salary_max": 0}
        result = map_job(raw)
        self.assertIsNone(result["compensation_min"])
        self.assertIsNone(result["compensation_max"])

    def test_salary_missing_becomes_none(self):
        raw = {k: v for k, v in SAMPLE_RAW.items() if k not in ("salary_min", "salary_max")}
        result = map_job(raw)
        self.assertIsNone(result["compensation_min"])
        self.assertIsNone(result["compensation_max"])


class MapJobLocationTest(unittest.TestCase):
    def test_specific_location(self):
        raw = {**SAMPLE_RAW, "location": "USA"}
        result = map_job(raw)
        self.assertEqual(result["countries_allowed"], ["USA"])

    def test_empty_location(self):
        raw = {**SAMPLE_RAW, "location": ""}
        result = map_job(raw)
        self.assertEqual(result["countries_allowed"], ["GLOBAL"])

    def test_missing_location(self):
        raw = {k: v for k, v in SAMPLE_RAW.items() if k != "location"}
        result = map_job(raw)
        self.assertEqual(result["countries_allowed"], ["GLOBAL"])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_remoteok_fetcher.py -k "MapJob" -v`
Expected: FAIL — `ImportError: cannot import name 'map_job'`

- [ ] **Step 3: Implement map_job**

Add to `agent_hub/agents/global_part_time/fetchers/remoteok.py`:

```python
from datetime import datetime, timezone

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
    published_at = (
        datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat() if epoch else None
    )

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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_remoteok_fetcher.py -v`
Expected: All tests PASS (StripHtml + MapJob)

- [ ] **Step 5: Commit**

```bash
git add tests/test_remoteok_fetcher.py \
        agent_hub/agents/global_part_time/fetchers/remoteok.py
git commit -m "feat: add map_job for RemoteOK → system schema conversion"
```

---

### Task 3: fetch — HTTP retrieval from RemoteOK API

**Files:**
- Modify: `tests/test_remoteok_fetcher.py`
- Modify: `agent_hub/agents/global_part_time/fetchers/remoteok.py`

- [ ] **Step 1: Write the failing tests for fetch**

Append to `tests/test_remoteok_fetcher.py`:

```python
import json
from unittest.mock import patch, MagicMock

from agent_hub.agents.global_part_time.fetchers.remoteok import fetch

METADATA = {"legal": "https://remoteok.com/legal"}

MOCK_API_RESPONSE = json.dumps([
    METADATA,
    {
        "id": "111",
        "slug": "job-1",
        "company": "Alpha",
        "position": "Dev",
        "description": "desc",
        "location": "Worldwide",
        "tags": ["python"],
        "salary_min": 0,
        "salary_max": 0,
        "url": "https://remoteok.com/remote-jobs/111",
        "apply_url": "",
        "epoch": 1752700800,
    },
    {
        "id": "222",
        "slug": "job-2",
        "company": "Beta",
        "position": "Designer",
        "description": "design",
        "location": "USA",
        "tags": ["figma"],
        "salary_min": 80000,
        "salary_max": 100000,
        "url": "https://remoteok.com/remote-jobs/222",
        "apply_url": "",
        "epoch": 1752700800,
    },
]).encode()


def _mock_urlopen(response_bytes: bytes):
    """Return a mock that behaves like urllib.request.urlopen context manager."""
    mock_response = MagicMock()
    mock_response.read.return_value = response_bytes
    mock_response.__enter__ = lambda s: s
    mock_response.__exit__ = MagicMock(return_value=False)
    return mock_response


class FetchTest(unittest.TestCase):
    @patch("agent_hub.agents.global_part_time.fetchers.remoteok.urlopen")
    def test_skips_metadata_element(self, mock_urlopen_fn):
        mock_urlopen_fn.return_value = _mock_urlopen(MOCK_API_RESPONSE)
        jobs = fetch()
        self.assertEqual(len(jobs), 2)
        self.assertEqual(jobs[0]["id"], "111")
        self.assertEqual(jobs[1]["id"], "222")

    @patch("agent_hub.agents.global_part_time.fetchers.remoteok.urlopen")
    def test_limit_truncates(self, mock_urlopen_fn):
        mock_urlopen_fn.return_value = _mock_urlopen(MOCK_API_RESPONSE)
        jobs = fetch(limit=1)
        self.assertEqual(len(jobs), 1)

    @patch("agent_hub.agents.global_part_time.fetchers.remoteok.urlopen")
    def test_tags_appended_to_url(self, mock_urlopen_fn):
        mock_urlopen_fn.return_value = _mock_urlopen(MOCK_API_RESPONSE)
        fetch(tags=["python", "react"])
        call_args = mock_urlopen_fn.call_args
        request = call_args[0][0]
        self.assertIn("tag=python", request.full_url)
        self.assertIn("tag=react", request.full_url)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_remoteok_fetcher.py::FetchTest -v`
Expected: FAIL — `ImportError: cannot import name 'fetch'`

- [ ] **Step 3: Implement fetch**

Add to `agent_hub/agents/global_part_time/fetchers/remoteok.py`:

```python
import json
from urllib.request import Request, urlopen

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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_remoteok_fetcher.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_remoteok_fetcher.py \
        agent_hub/agents/global_part_time/fetchers/remoteok.py
git commit -m "feat: add fetch() for RemoteOK API retrieval"
```

---

### Task 4: End-to-end sync test with mocked HTTP

**Files:**
- Modify: `tests/test_remoteok_fetcher.py`

- [ ] **Step 1: Write the end-to-end integration test**

Append to `tests/test_remoteok_fetcher.py`:

```python
from agent_hub.agents.global_part_time.fetchers.remoteok import fetch, map_job
from agent_hub.agents.global_part_time.repository import Repository
from agent_hub.agents.global_part_time.service import AgentService


REMOTEOK_SOURCE = {
    "name": "RemoteOK Public API",
    "source_type": "api",
    "base_url": "https://remoteok.com/api",
    "authorization_basis": "public API, attribution required",
    "allowed_paths": ["/api"],
    "prohibited_actions": [],
    "rate_limit": "60/hour",
    "retention_policy": "30 days",
}


class EndToEndSyncTest(unittest.TestCase):
    @patch("agent_hub.agents.global_part_time.fetchers.remoteok.urlopen")
    def test_full_pipeline(self, mock_urlopen_fn):
        mock_urlopen_fn.return_value = _mock_urlopen(MOCK_API_RESPONSE)

        # 1. Set up service
        repo = Repository(":memory:")
        service = AgentService(repo)

        # 2. Register and approve source
        source = service.create_source(REMOTEOK_SOURCE, "operator")
        service.review_source(source["id"], True, "operator")

        # 3. Fetch and map
        raw_jobs = fetch()
        mapped = [map_job(r) for r in raw_jobs]

        # 4. Sync
        result = service.sync_source(source["id"], mapped, "worker")

        self.assertEqual(result["received"], 2)
        self.assertEqual(result["imported"], 2)
        self.assertEqual(result["duplicates"], 0)
        self.assertEqual(result["rejected"], 0)

        # 5. Verify jobs are in the store
        jobs = repo.list("job")
        self.assertEqual(len(jobs), 2)
        titles = {j["title_original"] for j in jobs}
        self.assertIn("Dev", titles)
        self.assertIn("Designer", titles)

        # 6. Second sync should deduplicate
        mock_urlopen_fn.return_value = _mock_urlopen(MOCK_API_RESPONSE)
        raw_jobs2 = fetch()
        mapped2 = [map_job(r) for r in raw_jobs2]
        result2 = service.sync_source(source["id"], mapped2, "worker")
        self.assertEqual(result2["imported"], 0)
        self.assertEqual(result2["duplicates"], 2)
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `python -m pytest tests/test_remoteok_fetcher.py::EndToEndSyncTest -v`
Expected: PASS — all assertions hold because sync_source handles dedup via `dedup_key`

- [ ] **Step 3: Run the full test file**

Run: `python -m pytest tests/test_remoteok_fetcher.py -v`
Expected: All tests PASS

- [ ] **Step 4: Commit**

```bash
git add tests/test_remoteok_fetcher.py
git commit -m "test: add end-to-end RemoteOK sync integration test"
```

---

### Task 5: CLI script — sync_remoteok.py

**Files:**
- Create: `scripts/sync_remoteok.py`

- [ ] **Step 1: Create the scripts directory and CLI entry point**

Create `scripts/sync_remoteok.py`:

```python
#!/usr/bin/env python
"""CLI: register RemoteOK as a source, fetch jobs, and sync into the store.

Usage:
    python scripts/sync_remoteok.py
    python scripts/sync_remoteok.py --tags python react --limit 50
"""

from __future__ import annotations

import argparse
import sys

from agent_hub.agents.global_part_time.fetchers.remoteok import fetch, map_job
from agent_hub.agents.global_part_time.repository import Repository
from agent_hub.agents.global_part_time.service import AgentService


REMOTEOK_SOURCE = {
    "name": "RemoteOK Public API",
    "source_type": "api",
    "base_url": "https://remoteok.com/api",
    "authorization_basis": "public API, attribution required per RemoteOK terms",
    "allowed_paths": ["/api"],
    "prohibited_actions": [],
    "rate_limit": "60/hour",
    "retention_policy": "30 days",
}

ACTOR = "cli:sync_remoteok"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Sync RemoteOK jobs into the store")
    parser.add_argument("--tags", nargs="*", help="Filter by tags (e.g. python react)")
    parser.add_argument("--limit", type=int, default=200, help="Max jobs to fetch")
    parser.add_argument("--db", default=None, help="Database path (default: ./data/agent.db)")
    args = parser.parse_args(argv)

    repo = Repository(args.db)
    service = AgentService(repo)

    # Find or create the RemoteOK source
    existing = [s for s in repo.list("source") if s.get("name") == REMOTEOK_SOURCE["name"]]
    if existing:
        source = existing[0]
        print(f"Found existing source: {source['id']}")
    else:
        source = service.create_source(REMOTEOK_SOURCE, ACTOR)
        print(f"Registered source: {source['id']}")

    # Auto-approve if still pending
    if source.get("review_status") != "approved":
        source = service.review_source(source["id"], True, ACTOR, "auto-approved for CLI sync")
        print("Source approved.")

    # Fetch
    print(f"Fetching from RemoteOK (tags={args.tags}, limit={args.limit})...")
    try:
        raw_jobs = fetch(tags=args.tags, limit=args.limit)
    except Exception as e:
        print(f"Fetch failed: {e}", file=sys.stderr)
        sys.exit(1)
    print(f"Fetched {len(raw_jobs)} raw jobs.")

    if not raw_jobs:
        print("No jobs to sync.")
        return

    # Map
    mapped = [map_job(r) for r in raw_jobs]

    # Sync
    result = service.sync_source(source["id"], mapped, ACTOR)

    print(f"\n--- Sync Result ---")
    print(f"Received:       {result['received']}")
    print(f"Imported:        {result['imported']}")
    print(f"Duplicates:      {result['duplicates']}")
    print(f"Pending review:  {result['pending_review']}")
    print(f"Rejected:        {result['rejected']}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Verify the script runs with --help**

Run: `python scripts/sync_remoteok.py --help`
Expected: Prints usage info without errors

- [ ] **Step 3: Commit**

```bash
git add scripts/sync_remoteok.py
git commit -m "feat: add CLI script for RemoteOK sync pipeline"
```

---

### Task 6: Live smoke test — run the full pipeline

- [ ] **Step 1: Run ruff check**

Run: `ruff check agent_hub/agents/global_part_time/fetchers/ scripts/ tests/test_remoteok_fetcher.py`
Expected: No errors (fix any issues before proceeding)

- [ ] **Step 2: Run ruff format**

Run: `ruff format agent_hub/agents/global_part_time/fetchers/ scripts/ tests/test_remoteok_fetcher.py`
Expected: Files formatted

- [ ] **Step 3: Run the full test suite**

Run: `python -m pytest tests/test_remoteok_fetcher.py -v`
Expected: All tests PASS

- [ ] **Step 4: Run the CLI against the real RemoteOK API**

Run: `python scripts/sync_remoteok.py --tags python --limit 10`
Expected: Output like:
```
Registered source: <uuid>
Source approved.
Fetching from RemoteOK (tags=['python'], limit=10)...
Fetched 10 raw jobs.

--- Sync Result ---
Received:       10
Imported:        X
Duplicates:      Y
Pending review:  Z
Rejected:        W
```

- [ ] **Step 5: Commit any lint/format fixes**

```bash
git add -u
git commit -m "style: apply ruff formatting to RemoteOK fetcher"
```

- [ ] **Step 6: Final commit for any remaining changes**

Run `git status` and commit if anything is left.
