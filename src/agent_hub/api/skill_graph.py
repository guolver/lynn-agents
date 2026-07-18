"""Skill knowledge graph visualization API."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter


def create_skill_graph_router(service: Any) -> APIRouter:
    """Create a router exposing the skill graph for frontend visualization."""

    router = APIRouter(prefix="/platform/v1", tags=["skill-graph"])

    @router.get("/skill-graph")
    def get_skill_graph() -> dict[str, Any]:
        data = service.graph()
        return {"nodes": data["nodes"], "links": data["links"]}

    return router
