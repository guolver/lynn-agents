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
        # Distinct title so this fixture doesn't collide with the job above
        # under dedup_key() (company/title/countries/description-based) when
        # both are synced in the same batch.
        {
            **SAMPLE_RAW,
            "url": "https://www.workingnomads.com/job/go/2/",
            "title": "Senior Backend Engineer",
        },
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
