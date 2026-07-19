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
    service.run_matches.assert_called_once_with("c1", "test", 10, exclude_job_ids=None)


def test_execute_run_matches_attaches_recommendation_summary(monkeypatch):
    import agent_hub.agents.global_part_time.chat_tools as chat_tools

    service = MagicMock()
    service.run_matches.return_value = {
        "matches": [{"id": "m1", "job_id": "j1", "score": 0.8, "reasons": ["技能匹配"]}],
        "filtered": [],
    }
    service.repo.list.return_value = [
        {"id": "j1", "title_original": "Frontend", "company_name": "Example"}
    ]
    service.get_candidate.return_value = {"id": "c1", "skills": [{"name": "React"}]}
    monkeypatch.setattr(
        chat_tools,
        "generate_recommendation_summaries",
        lambda candidate, matches, jobs_by_id: {"j1": "你的 React 经验与岗位职责契合。"},
    )

    result = execute_tool("run_matches", {"candidate_id": "c1"}, service=service, actor="test")

    assert result["matches"][0]["recommendation_summary"] == "你的 React 经验与岗位职责契合。"
    service.repo.put.assert_called_once_with("match", result["matches"][0])


def test_execute_run_matches_keeps_matches_when_summary_is_unavailable(monkeypatch):
    import agent_hub.agents.global_part_time.chat_tools as chat_tools

    service = MagicMock()
    service.run_matches.return_value = {
        "matches": [{"id": "m1", "job_id": "j1", "score": 0.8, "reasons": ["技能匹配"]}],
        "filtered": [],
    }
    service.repo.list.return_value = [
        {"id": "j1", "title_original": "Frontend", "company_name": "Example"}
    ]
    service.get_candidate.return_value = {"id": "c1"}
    monkeypatch.setattr(
        chat_tools,
        "generate_recommendation_summaries",
        lambda candidate, matches, jobs_by_id: {},
    )

    result = execute_tool("run_matches", {"candidate_id": "c1"}, service=service, actor="test")

    assert len(result["matches"]) == 1
    assert "recommendation_summary" not in result["matches"][0]


def test_execute_run_matches_keeps_matches_when_explainer_raises(monkeypatch):
    import agent_hub.agents.global_part_time.chat_tools as chat_tools

    service = MagicMock()
    service.run_matches.return_value = {
        "matches": [{"id": "m1", "job_id": "j1", "score": 0.8, "reasons": ["技能匹配"]}],
        "filtered": [],
    }
    service.repo.list.return_value = [
        {"id": "j1", "title_original": "Frontend", "company_name": "Example"}
    ]
    service.get_candidate.return_value = {"id": "c1"}

    def raise_explainer_error(candidate, matches, jobs_by_id):
        raise RuntimeError("DeepSeek unavailable")

    monkeypatch.setattr(
        chat_tools,
        "generate_recommendation_summaries",
        raise_explainer_error,
    )

    result = execute_tool("run_matches", {"candidate_id": "c1"}, service=service, actor="test")

    assert len(result["matches"]) == 1
    assert "error" not in result


def test_execute_unknown_tool():
    service = MagicMock()
    result = execute_tool("nonexistent", {}, service=service, actor="test")
    assert "error" in result


def test_execute_parse_resume_persists_resume_text(monkeypatch):
    import agent_hub.agents.global_part_time.resume_parser as rp

    monkeypatch.setattr(rp, "parse_resume", lambda text: {"country": "CN", "skills": []})
    service = MagicMock()
    service.create_candidate.return_value = {"id": "c1", "resume_text": "张三的简历原文"}
    result = execute_tool(
        "parse_resume", {"pdf_text": "张三的简历原文"}, service=service, actor="t"
    )
    # 建档 payload 里带原文
    created_payload = service.create_candidate.call_args[0][0]
    assert created_payload["resume_text"] == "张三的简历原文"
    # 工具返回值不回显原文（避免撑爆 LLM 上下文与 tool 消息）
    assert "resume_text" not in result["candidate"]


def test_execute_parse_resume_caps_resume_text_at_20000(monkeypatch):
    import agent_hub.agents.global_part_time.resume_parser as rp

    monkeypatch.setattr(rp, "parse_resume", lambda text: {"country": "CN", "skills": []})
    service = MagicMock()
    service.create_candidate.return_value = {"id": "c1"}
    execute_tool("parse_resume", {"pdf_text": "x" * 25000}, service=service, actor="t")
    created_payload = service.create_candidate.call_args[0][0]
    assert len(created_payload["resume_text"]) == 20000


def test_get_my_profile_truncates_long_resume_text():
    service = MagicMock()
    service.get_candidate.return_value = {"id": "c1", "resume_text": "y" * 7000}
    result = execute_tool("get_my_profile", {"candidate_id": "c1"}, service=service, actor="t")
    assert result["resume_text"].endswith("...(truncated)")
    assert len(result["resume_text"]) == 6000 + len("...(truncated)")


def test_get_my_profile_without_resume_text_unchanged():
    service = MagicMock()
    service.get_candidate.return_value = {"id": "c1", "country": "CN"}
    result = execute_tool("get_my_profile", {"candidate_id": "c1"}, service=service, actor="t")
    assert "resume_text" not in result
