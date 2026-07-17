#!/usr/bin/env python
"""CLI: register Remotive as a source, fetch jobs, and sync into the store.

Usage:
    python scripts/sync_remotive.py
    python scripts/sync_remotive.py --category software-dev --limit 50
    python scripts/sync_remotive.py --search python --limit 20
"""

from __future__ import annotations

import argparse
import sys

from agent_hub.agents.global_part_time.fetchers.remotive import fetch, map_job
from agent_hub.agents.global_part_time.repository import Repository
from agent_hub.agents.global_part_time.service import AgentService


REMOTIVE_SOURCE = {
    "name": "Remotive Public API",
    "source_type": "api",
    "base_url": "https://remotive.com/api/remote-jobs",
    "authorization_basis": "public API, attribution required per Remotive terms",
    "allowed_paths": ["/api"],
    "prohibited_actions": [],
    "rate_limit": "4/day",
    "retention_policy": "30 days",
}

ACTOR = "cli:sync_remotive"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Sync Remotive jobs into the store")
    parser.add_argument("--category", help="Filter by category (e.g. software-dev)")
    parser.add_argument("--search", help="Search query (e.g. python)")
    parser.add_argument("--limit", type=int, default=200, help="Max jobs to fetch")
    parser.add_argument("--db", default=None, help="Database path (default: ./data/agent.db)")
    args = parser.parse_args(argv)

    repo = Repository(args.db)
    service = AgentService(repo)

    # Find or create the Remotive source
    existing = [s for s in repo.list("source") if s.get("name") == REMOTIVE_SOURCE["name"]]
    if existing:
        source = existing[0]
        print(f"Found existing source: {source['id']}")
    else:
        source = service.create_source(REMOTIVE_SOURCE, ACTOR)
        print(f"Registered source: {source['id']}")

    # Auto-approve if still pending
    if source.get("review_status") != "approved":
        source = service.review_source(source["id"], True, ACTOR, "auto-approved for CLI sync")
        print("Source approved.")

    # Fetch
    print(
        f"Fetching from Remotive (category={args.category}, search={args.search}, limit={args.limit})..."
    )
    try:
        raw_jobs = fetch(category=args.category, search=args.search, limit=args.limit)
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
