#!/usr/bin/env python
"""CLI: register Himalayas as a source, fetch jobs, and sync into the store.

Usage:
    python scripts/sync_himalayas.py
    python scripts/sync_himalayas.py --limit 500
"""

from __future__ import annotations

import argparse
import sys

from agent_hub.agents.global_part_time.fetchers.himalayas import fetch, map_job
from agent_hub.agents.global_part_time.service import AgentService
from agent_hub.database.config import create_repository


HIMALAYAS_SOURCE = {
    "name": "Himalayas Public API",
    "source_type": "api",
    "base_url": "https://himalayas.app/jobs/api",
    "authorization_basis": "public API, attribution required per Himalayas terms",
    "allowed_paths": ["/jobs/api"],
    "prohibited_actions": [],
    "rate_limit": "60/hour",
    "retention_policy": "30 days",
}

ACTOR = "cli:sync_himalayas"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Sync Himalayas jobs into the store")
    parser.add_argument("--limit", type=int, default=200, help="Max jobs to fetch")
    args = parser.parse_args(argv)

    repo = create_repository()
    service = AgentService(repo)

    # Find or create the Himalayas source
    existing = [s for s in repo.list("source") if s.get("name") == HIMALAYAS_SOURCE["name"]]
    if existing:
        source = existing[0]
        print(f"Found existing source: {source['id']}")
    else:
        source = service.create_source(HIMALAYAS_SOURCE, ACTOR)
        print(f"Registered source: {source['id']}")

    # Auto-approve if still pending
    if source.get("review_status") != "approved":
        source = service.review_source(source["id"], True, ACTOR, "auto-approved for CLI sync")
        print("Source approved.")

    # Fetch (paginated internally, 20 per request)
    print(f"Fetching from Himalayas (limit={args.limit})...")
    try:
        raw_jobs = fetch(limit=args.limit)
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
