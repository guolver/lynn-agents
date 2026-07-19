"""Tests for batched LLM recommendation summaries."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

from agent_hub.agents.global_part_time.recommendation_explainer import (
    generate_recommendation_summaries,
)


def _response(content: str):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


def _inputs(count: int = 2):
    candidate = {
        "desired_roles": ["Frontend Engineer"],
        "skills": [{"name": "React"}, {"name": "TypeScript"}],
        "resume_summary": "负责复杂 Web 产品和可视化编辑器。",
    }
    matches = [
        {"job_id": f"j{i}", "reasons": ["React 技能与职位要求直接匹配"]}
        for i in range(1, count + 1)
    ]
    jobs_by_id = {
        f"j{i}": {
            "id": f"j{i}",
            "title_original": f"Frontend Engineer {i}",
            "company_name": "Example",
            "description_original": "Build React applications.",
        }
        for i in range(1, count + 1)
    }
    return candidate, matches, jobs_by_id


def test_generates_one_batched_request_and_validates_output(monkeypatch):
    import agent_hub.agents.global_part_time.recommendation_explainer as explainer

    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    candidate, matches, jobs_by_id = _inputs(6)
    content = json.dumps(
        {
            "j1": "你的 React 经验与该岗位的前端职责高度契合。",
            "j2": "第二个岗位总结",
            "j5": "x" * 121,
            "j6": "不应处理第六个岗位",
            "unknown": "未知岗位",
        },
        ensure_ascii=False,
    )
    client = MagicMock()
    client.chat.completions.create.return_value = _response(content)
    openai = MagicMock(return_value=client)
    monkeypatch.setattr(explainer, "OpenAI", openai)

    summaries = generate_recommendation_summaries(candidate, matches, jobs_by_id)

    assert summaries == {
        "j1": "你的 React 经验与该岗位的前端职责高度契合。",
        "j2": "第二个岗位总结",
    }
    assert client.chat.completions.create.call_count == 1
    request = client.chat.completions.create.call_args.kwargs
    assert "j5" in request["messages"][1]["content"]
    assert "j6" not in request["messages"][1]["content"]


def test_without_api_key_returns_empty_without_creating_client(monkeypatch):
    import agent_hub.agents.global_part_time.recommendation_explainer as explainer

    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    candidate, matches, jobs_by_id = _inputs()
    openai = MagicMock()
    monkeypatch.setattr(explainer, "OpenAI", openai)

    assert generate_recommendation_summaries(candidate, matches, jobs_by_id) == {}
    openai.assert_not_called()


def test_invalid_json_degrades_to_empty(monkeypatch):
    import agent_hub.agents.global_part_time.recommendation_explainer as explainer

    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    candidate, matches, jobs_by_id = _inputs()
    client = MagicMock()
    client.chat.completions.create.return_value = _response("not-json")
    monkeypatch.setattr(explainer, "OpenAI", MagicMock(return_value=client))

    assert generate_recommendation_summaries(candidate, matches, jobs_by_id) == {}


def test_api_error_degrades_to_empty(monkeypatch):
    import agent_hub.agents.global_part_time.recommendation_explainer as explainer

    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    candidate, matches, jobs_by_id = _inputs()
    client = MagicMock()
    client.chat.completions.create.side_effect = RuntimeError("provider unavailable")
    monkeypatch.setattr(explainer, "OpenAI", MagicMock(return_value=client))

    assert generate_recommendation_summaries(candidate, matches, jobs_by_id) == {}
