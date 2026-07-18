"""resume_parser 的 resume_summary 提取测试（LLM 调用全部 mock）。"""

from __future__ import annotations

import json
import os
import unittest
from unittest import mock

from agent_hub.agents.global_part_time.resume_parser import parse_resume


def _fake_response(content: str):
    message = mock.Mock()
    message.content = content
    choice = mock.Mock()
    choice.message = message
    response = mock.Mock()
    response.choices = [choice]
    return response


class ResumeSummaryTests(unittest.TestCase):
    def _parse_with(self, payload: dict) -> dict:
        with (
            mock.patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test-key"}),
            mock.patch("agent_hub.agents.global_part_time.resume_parser.OpenAI") as openai_cls,
        ):
            client = openai_cls.return_value
            client.chat.completions.create.return_value = _fake_response(json.dumps(payload))
            return parse_resume("resume text")

    def test_resume_summary_passthrough(self):
        parsed = self._parse_with(
            {"country": "CN", "resume_summary": "五年后端开发，主导支付系统重构"}
        )
        self.assertEqual(parsed["resume_summary"], "五年后端开发，主导支付系统重构")

    def test_resume_summary_defaults_to_none(self):
        parsed = self._parse_with({"country": "CN"})
        self.assertIsNone(parsed["resume_summary"])

    def test_prompt_mentions_resume_summary(self):
        from agent_hub.agents.global_part_time.resume_parser import SYSTEM_PROMPT

        self.assertIn("resume_summary", SYSTEM_PROMPT)


if __name__ == "__main__":
    unittest.main()
