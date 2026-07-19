#!/usr/bin/env python
"""CLI: register Jobicy as a source, fetch jobs, and sync into the store.

Usage:
    python scripts/sync_jobicy.py
    python scripts/sync_jobicy.py --geo usa --industry engineering --count 100
    python scripts/sync_jobicy.py --tag python --count 50
"""

from __future__ import annotations

import argparse
import sys

from agent_hub.agents.global_part_time.fetchers.jobicy import fetch, map_job
from agent_hub.agents.global_part_time.service import AgentService
from agent_hub.database.config import create_repository


JOBICY_SOURCE = {
    "name": "Jobicy Public API",
    "source_type": "api",
    "base_url": "https://jobicy.com/api/v2/remote-jobs",
    "authorization_basis": "public API, attribution required per Jobicy terms",
    "allowed_paths": ["/api/v2/remote-jobs"],
    "prohibited_actions": [],
    "rate_limit": "60/hour",
    "retention_policy": "30 days",
}

ACTOR = "cli:sync_jobicy"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Sync Jobicy jobs into the store")
    parser.add_argument("--geo", help="Filter by geography (e.g. usa, uk, europe)")
    parser.add_argument("--industry", help="Filter by industry (e.g. engineering, marketing)")
    parser.add_argument("--tag", help="Search by keyword in title/description")
    parser.add_argument("--count", type=int, default=100, help="Jobs per request (max 100)")
    parser.add_argument("--limit", type=int, default=200, help="Max jobs to fetch total")
    args = parser.parse_args(argv)

    repo = create_repository()
    service = AgentService(repo)

    # Find or create the Jobicy source
    existing = [s for s in repo.list("source") if s.get("name") == JOBICY_SOURCE["name"]]
    if existing:
        source = existing[0]
        print(f"Found existing source: {source['id']}")
    else:
        source = service.create_source(JOBICY_SOURCE, ACTOR)
        print(f"Registered source: {source['id']}")

    # Auto-approve if still pending
    if source.get("review_status") != "approved":
        source = service.review_source(source["id"], True, ACTOR, "auto-approved for CLI sync")
        print("Source approved.")

    # Fetch
    print(f"Fetching from Jobicy (geo={args.geo}, industry={args.industry}, tag={args.tag})...")
    try:
        raw_jobs = fetch(
            geo=args.geo,
            industry=args.industry,
            tag=args.tag,
            count=args.count,
            limit=args.limit,
        )
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

    print("\n--- Sync Result ---")
    print(f"Received:       {result['received']}")
    print(f"Imported:        {result['imported']}")
    print(f"Duplicates:      {result['duplicates']}")
    print(f"Pending review:  {result['pending_review']}")
    print(f"Rejected:        {result['rejected']}")


if __name__ == "__main__":
    main()
