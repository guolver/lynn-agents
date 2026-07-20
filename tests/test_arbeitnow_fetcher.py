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
            # Distinct title so this fixture doesn't collide with job-1 under
            # dedup_key() (company/title/countries/description-based) when
            # both are synced in the same batch.
            {**SAMPLE_RAW, "slug": "job-3", "remote": True, "title": "Data Platform Engineer"},
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

EMPTY_PAGE = json.dumps({"data": [], "links": {"next": None}, "meta": {"current_page": 3}}).encode()


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
