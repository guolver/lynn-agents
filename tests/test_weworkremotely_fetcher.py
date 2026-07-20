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
