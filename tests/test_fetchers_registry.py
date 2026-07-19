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
