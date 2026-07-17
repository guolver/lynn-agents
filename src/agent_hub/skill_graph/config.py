"""Neo4j connection factory."""

from __future__ import annotations

import os
from typing import Any

import neo4j


def create_neo4j_driver(
    uri: str | None = None,
    auth: tuple[str, str] | None = None,
    **kwargs: Any,
) -> neo4j.Driver:
    """Create a Neo4j driver from explicit args or environment variables.

    Env vars: NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD.
    """
    resolved_uri = uri or os.getenv("NEO4J_URI", "bolt://localhost:7687")
    resolved_auth = auth or (
        os.getenv("NEO4J_USER", "neo4j"),
        os.getenv("NEO4J_PASSWORD", "password"),
    )
    return neo4j.GraphDatabase.driver(resolved_uri, auth=resolved_auth, **kwargs)
