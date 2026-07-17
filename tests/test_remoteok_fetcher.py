"""Tests for the RemoteOK fetcher module."""

import json
import unittest
from unittest.mock import MagicMock, patch

from agent_hub.agents.global_part_time.fetchers.remoteok import fetch, map_job, strip_html


class StripHtmlTest(unittest.TestCase):
    def test_removes_tags(self):
        self.assertEqual(strip_html("<p>Hello <b>world</b></p>"), "Hello world")

    def test_preserves_plain_text(self):
        self.assertEqual(strip_html("no tags here"), "no tags here")

    def test_empty_string(self):
        self.assertEqual(strip_html(""), "")

    def test_nested_tags(self):
        self.assertEqual(strip_html("<div><ul><li>item</li></ul></div>"), "item")

    def test_br_adds_space(self):
        result = strip_html("line1<br>line2<br/>line3")
        self.assertIn("line1", result)
        self.assertIn("line2", result)

    def test_strips_whitespace(self):
        result = strip_html("  <p>  spaced  </p>  ")
        self.assertEqual(result, "spaced")


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
    "epoch": 1784160000,
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
        self.assertEqual(self.result["description_original"], "Build APIs for our platform.")

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


METADATA = {"legal": "https://remoteok.com/legal"}

MOCK_API_RESPONSE = json.dumps(
    [
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
    ]
).encode()


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
