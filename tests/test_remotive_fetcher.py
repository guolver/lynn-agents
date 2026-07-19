"""Tests for the Remotive fetcher module."""

import json
import unittest
from unittest.mock import MagicMock, patch

from agent_hub.agents.global_part_time.fetchers.remotive import fetch, map_job, parse_salary
from tests.inmemory_repo import InMemoryRepository as Repository
from agent_hub.agents.global_part_time.service import AgentService


class ParseSalaryTest(unittest.TestCase):
    def test_hourly_range(self):
        min_val, max_val, period = parse_salary("$90 - $150 /hour")
        self.assertEqual(min_val, 90)
        self.assertEqual(max_val, 150)
        self.assertEqual(period, "hour")

    def test_annual_range(self):
        min_val, max_val, period = parse_salary("$150,000 - $230,000")
        self.assertAlmostEqual(min_val, 72.12, places=2)
        self.assertAlmostEqual(max_val, 110.58, places=2)

    def test_annual_k_suffix(self):
        min_val, max_val, period = parse_salary("$150k - $230k")
        self.assertAlmostEqual(min_val, 72.12, places=2)
        self.assertAlmostEqual(max_val, 110.58, places=2)

    def test_empty_string(self):
        min_val, max_val, _ = parse_salary("")
        self.assertIsNone(min_val)
        self.assertIsNone(max_val)

    def test_no_salary(self):
        min_val, max_val, _ = parse_salary("Competitive")
        self.assertIsNone(min_val)
        self.assertIsNone(max_val)

    def test_single_value_annual(self):
        min_val, max_val, _ = parse_salary("$120,000")
        self.assertAlmostEqual(min_val, 57.69, places=2)
        self.assertIsNone(max_val)


SAMPLE_RAW = {
    "id": 1919265,
    "url": "https://remotive.com/remote-jobs/software-development/senior-dev-1919265",
    "title": "Senior Software Developer",
    "company_name": "Acme Corp",
    "company_logo": "https://remotive.com/job/1919265/logo",
    "category": "Software Development",
    "tags": ["python", "react", "aws"],
    "job_type": "contract",
    "publication_date": "2026-07-16T10:10:51",
    "candidate_required_location": "Americas, Europe",
    "salary": "$90 - $150 /hour",
    "description": "<p>Build <b>APIs</b> for our platform.</p>",
}


class MapJobCompleteTest(unittest.TestCase):
    def setUp(self):
        self.result = map_job(SAMPLE_RAW)

    def test_source_job_id(self):
        self.assertEqual(self.result["source_job_id"], "1919265")

    def test_canonical_url(self):
        self.assertIn("remotive.com", self.result["canonical_url"])

    def test_title(self):
        self.assertEqual(self.result["title_original"], "Senior Software Developer")

    def test_company(self):
        self.assertEqual(self.result["company_name"], "Acme Corp")

    def test_description_stripped(self):
        self.assertEqual(self.result["description_original"], "Build APIs for our platform.")

    def test_skills(self):
        self.assertEqual(self.result["skills"], ["python", "react", "aws"])

    def test_categories_from_category_field(self):
        self.assertEqual(self.result["categories"], ["Software Development"])

    def test_location_split(self):
        self.assertEqual(self.result["countries_allowed"], ["Americas", "Europe"])

    def test_work_mode_remote(self):
        self.assertEqual(self.result["work_mode"], "remote")

    def test_hourly_salary(self):
        self.assertEqual(self.result["compensation_min"], 90)
        self.assertEqual(self.result["compensation_max"], 150)

    def test_compensation_currency_and_period(self):
        self.assertEqual(self.result["compensation_currency"], "USD")
        self.assertEqual(self.result["compensation_period"], "hour")

    def test_employment_type(self):
        self.assertEqual(self.result["employment_type"], "part_time")

    def test_published_at(self):
        self.assertEqual(self.result["published_at"], "2026-07-16T10:10:51")

    def test_extraction_confidence(self):
        self.assertEqual(self.result["extraction_confidence"], 0.7)

    def test_quality_score(self):
        self.assertEqual(self.result["quality_score"], 0.75)


class MapJobLocationTest(unittest.TestCase):
    def test_worldwide(self):
        raw = {**SAMPLE_RAW, "candidate_required_location": "Worldwide"}
        self.assertEqual(map_job(raw)["countries_allowed"], ["GLOBAL"])

    def test_anywhere(self):
        raw = {**SAMPLE_RAW, "candidate_required_location": "Anywhere"}
        self.assertEqual(map_job(raw)["countries_allowed"], ["GLOBAL"])

    def test_empty_location(self):
        raw = {**SAMPLE_RAW, "candidate_required_location": ""}
        self.assertEqual(map_job(raw)["countries_allowed"], ["GLOBAL"])

    def test_single_location(self):
        raw = {**SAMPLE_RAW, "candidate_required_location": "USA"}
        self.assertEqual(map_job(raw)["countries_allowed"], ["USA"])


class MapJobCategoryFallbackTest(unittest.TestCase):
    def test_no_category_uses_tags(self):
        raw = {**SAMPLE_RAW, "category": ""}
        self.assertEqual(map_job(raw)["categories"], ["python", "react", "aws"])


MOCK_API_RESPONSE = json.dumps(
    {
        "job-count": 2,
        "jobs": [
            {
                "id": 111,
                "url": "https://remotive.com/remote-jobs/software-development/dev-111",
                "title": "Dev",
                "company_name": "Alpha",
                "category": "Software Development",
                "tags": ["python"],
                "job_type": "contract",
                "publication_date": "2026-07-16T10:00:00",
                "candidate_required_location": "Worldwide",
                "salary": "",
                "description": "desc",
            },
            {
                "id": 222,
                "url": "https://remotive.com/remote-jobs/design/designer-222",
                "title": "Designer",
                "company_name": "Beta",
                "category": "Design",
                "tags": ["figma"],
                "job_type": "full_time",
                "publication_date": "2026-07-16T11:00:00",
                "candidate_required_location": "USA, Canada",
                "salary": "$80,000 - $120,000",
                "description": "design",
            },
        ],
    }
).encode()


def _mock_urlopen(response_bytes: bytes):
    mock_response = MagicMock()
    mock_response.read.return_value = response_bytes
    mock_response.__enter__ = lambda s: s
    mock_response.__exit__ = MagicMock(return_value=False)
    return mock_response


class FetchTest(unittest.TestCase):
    @patch("agent_hub.agents.global_part_time.fetchers.remotive.urlopen")
    def test_returns_jobs_array(self, mock_urlopen_fn):
        mock_urlopen_fn.return_value = _mock_urlopen(MOCK_API_RESPONSE)
        jobs = fetch()
        self.assertEqual(len(jobs), 2)
        self.assertEqual(jobs[0]["id"], 111)

    @patch("agent_hub.agents.global_part_time.fetchers.remotive.urlopen")
    def test_limit_truncates(self, mock_urlopen_fn):
        mock_urlopen_fn.return_value = _mock_urlopen(MOCK_API_RESPONSE)
        jobs = fetch(limit=1)
        self.assertEqual(len(jobs), 1)

    @patch("agent_hub.agents.global_part_time.fetchers.remotive.urlopen")
    def test_category_in_url(self, mock_urlopen_fn):
        mock_urlopen_fn.return_value = _mock_urlopen(MOCK_API_RESPONSE)
        fetch(category="software-dev")
        request = mock_urlopen_fn.call_args[0][0]
        self.assertIn("category=software-dev", request.full_url)

    @patch("agent_hub.agents.global_part_time.fetchers.remotive.urlopen")
    def test_search_in_url(self, mock_urlopen_fn):
        mock_urlopen_fn.return_value = _mock_urlopen(MOCK_API_RESPONSE)
        fetch(search="python")
        request = mock_urlopen_fn.call_args[0][0]
        self.assertIn("search=python", request.full_url)


REMOTIVE_SOURCE = {
    "name": "Remotive Public API",
    "source_type": "api",
    "base_url": "https://remotive.com/api/remote-jobs",
    "authorization_basis": "public API, attribution required",
    "allowed_paths": ["/api"],
    "prohibited_actions": [],
    "rate_limit": "4/day",
    "retention_policy": "30 days",
}


class EndToEndSyncTest(unittest.TestCase):
    @patch("agent_hub.agents.global_part_time.fetchers.remotive.urlopen")
    def test_full_pipeline(self, mock_urlopen_fn):
        mock_urlopen_fn.return_value = _mock_urlopen(MOCK_API_RESPONSE)

        repo = Repository(":memory:")
        service = AgentService(repo)

        source = service.create_source(REMOTIVE_SOURCE, "operator")
        service.review_source(source["id"], True, "operator")

        raw_jobs = fetch()
        mapped = [map_job(r) for r in raw_jobs]
        result = service.sync_source(source["id"], mapped, "worker")

        self.assertEqual(result["received"], 2)
        self.assertEqual(result["imported"], 2)
        self.assertEqual(result["duplicates"], 0)

        jobs = repo.list("job")
        self.assertEqual(len(jobs), 2)

        # Second sync deduplicates
        mock_urlopen_fn.return_value = _mock_urlopen(MOCK_API_RESPONSE)
        result2 = service.sync_source(source["id"], [map_job(r) for r in fetch()], "worker")
        self.assertEqual(result2["imported"], 0)
        self.assertEqual(result2["duplicates"], 2)
