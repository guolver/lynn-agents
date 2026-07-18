"""Tests for chat tool definitions and executor."""

from __future__ import annotations

from unittest.mock import MagicMock

from agent_hub.agents.global_part_time.chat_tools import (
    TOOL_DEFINITIONS,
    execute_tool,
)


def test_tool_definitions_are_valid():
    """Each tool must have name, description, and parameters."""
    assert len(TOOL_DEFINITIONS) >= 5
    for tool in TOOL_DEFINITIONS:
        assert "function" in tool
        assert "name" in tool["function"]
        assert "description" in tool["function"]
        assert "parameters" in tool["function"]


def test_execute_get_my_profile():
    service = MagicMock()
    service.get_candidate.return_value = {
        "id": "c1",
        "country": "US",
        "skills": [{"name": "python", "level": 4}],
    }
    result = execute_tool(
        "get_my_profile",
        {"candidate_id": "c1"},
        service=service,
        actor="test",
    )
    assert result["id"] == "c1"
    service.get_candidate.assert_called_once_with("c1")


def test_execute_run_matches():
    service = MagicMock()
    service.run_matches.return_value = {
        "matches": [{"id": "m1", "score": 0.8}],
        "filtered": [],
    }
    result = execute_tool(
        "run_matches",
        {"candidate_id": "c1", "limit": 10},
        service=service,
        actor="test",
    )
    assert len(result["matches"]) == 1
    service.run_matches.assert_called_once_with("c1", "test", 10)


def test_execute_unknown_tool():
    service = MagicMock()
    result = execute_tool("nonexistent", {}, service=service, actor="test")
    assert "error" in result
