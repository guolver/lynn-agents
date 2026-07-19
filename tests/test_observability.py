"""可观测性单测：no-op 降级行为 + stream_response 埋点完整性（不依赖真实网络）。"""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from agent_hub import observability
from agent_hub.agents.global_part_time import chat_service as chat_service_module
from agent_hub.agents.global_part_time.chat_service import ChatService


class NoopFallbackTest(unittest.TestCase):
    def setUp(self):
        observability.reset_tracer()

    def tearDown(self):
        observability.reset_tracer()

    def test_no_keys_returns_noop(self):
        with patch.dict("os.environ", {}, clear=False):
            for key in ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY"):
                patch.dict("os.environ", {key: ""}).start()
            tracer = observability.get_chat_tracer()
        self.assertFalse(tracer.enabled)

    def test_noop_interface_is_complete(self):
        turn = observability.NoopTracer().start_turn(
            session_id="s", actor="a", user_message="m", candidate_id=None
        )
        turn.generation(name="g", model="m", input_messages=[], parameters={}).end(output=None)
        turn.tool(name="t", arguments={}).end(output=None)
        turn.end(output="done")  # 不抛任何异常即通过

    def test_singleton_cached(self):
        first = observability.get_chat_tracer()
        self.assertIs(first, observability.get_chat_tracer())


class RecordingTracer:
    """记录所有埋点调用，供断言。"""

    enabled = True

    def __init__(self):
        self.events = []

    def start_turn(self, **kwargs):
        self.events.append(("turn_start", kwargs))
        outer = self

        class Turn:
            def generation(self, **kw):
                outer.events.append(("generation_start", kw))

                class Handle:
                    def end(self, **end_kw):
                        outer.events.append(("generation_end", end_kw))

                return Handle()

            def tool(self, **kw):
                outer.events.append(("tool_start", kw))

                class Handle:
                    def end(self, **end_kw):
                        outer.events.append(("tool_end", end_kw))

                return Handle()

            def end(self, **kw):
                outer.events.append(("turn_end", kw))

        return Turn()


class FakeRepo:
    """最小内存仓储：仅覆盖 stream_response 用到的方法。"""

    def __init__(self):
        self.rows = {"chat_session": {}, "chat_message": {}}

    def put(self, kind, payload):
        self.rows[kind][payload["id"]] = dict(payload)
        return payload

    def get(self, kind, item_id):
        return self.rows[kind].get(item_id)

    def list_by_session(self, session_id):
        return [m for m in self.rows["chat_message"].values() if m["session_id"] == session_id]


def _chunk(content=None, tool_call=None, usage=None):
    delta = SimpleNamespace(content=content, tool_calls=tool_call and [tool_call])
    choices = [] if content is None and tool_call is None else [SimpleNamespace(delta=delta)]
    return SimpleNamespace(choices=choices, usage=usage)


def _usage(prompt, completion):
    return SimpleNamespace(
        prompt_tokens=prompt, completion_tokens=completion, total_tokens=prompt + completion
    )


class FakeCompletions:
    """第一轮返回一个 search_jobs 工具调用，第二轮返回纯文本。"""

    def __init__(self):
        self.calls = 0

    def create(self, **kwargs):
        self.calls += 1
        if self.calls == 1:
            tc = SimpleNamespace(
                index=0,
                id="t1",
                function=SimpleNamespace(name="search_jobs", arguments='{"keyword": "python"}'),
            )
            return iter([_chunk(tool_call=tc), _chunk(usage=_usage(100, 20))])
        return iter([_chunk(content="给你找到了"), _chunk(usage=_usage(200, 10))])


class StreamInstrumentationTest(unittest.TestCase):
    def test_full_turn_records_generations_tools_and_usage(self):
        repo = FakeRepo()
        repo.put("chat_session", {"id": "sess-1", "actor": "tester", "candidate_id": None})
        tracer = RecordingTracer()
        service = ChatService(service=None, repo=repo, tracer=tracer)

        fake_completions = FakeCompletions()
        fake_openai = SimpleNamespace(chat=SimpleNamespace(completions=fake_completions))

        with (
            patch.dict("os.environ", {"DEEPSEEK_API_KEY": "test-key"}),
            patch("openai.OpenAI", return_value=fake_openai),
            patch.object(
                chat_service_module, "execute_tool", return_value={"jobs": [], "total": 0}
            ),
        ):
            events = list(service.stream_response("sess-1", "有 python 工作吗"))

        self.assertEqual(events[-1]["event"], "done")
        kinds = [k for k, _ in tracer.events]
        self.assertEqual(
            kinds,
            [
                "turn_start",
                "generation_start",
                "generation_end",
                "tool_start",
                "tool_end",
                "generation_start",
                "generation_end",
                "turn_end",
            ],
        )
        by_kind = {}
        for kind, payload in tracer.events:
            by_kind.setdefault(kind, []).append(payload)
        # token 用量来自 include_usage 的末尾 chunk
        self.assertEqual(
            by_kind["generation_end"][0]["usage"],
            {
                "input": 100,
                "output": 20,
                "total": 120,
            },
        )
        self.assertEqual(by_kind["tool_start"][0]["name"], "search_jobs")
        self.assertEqual(by_kind["turn_end"][0]["output"], "给你找到了")
        self.assertIsNone(by_kind["turn_end"][0]["error"])

    def test_interrupted_turn_marked_on_early_abandon(self):
        repo = FakeRepo()
        repo.put("chat_session", {"id": "sess-2", "actor": "tester", "candidate_id": None})
        tracer = RecordingTracer()
        service = ChatService(service=None, repo=repo, tracer=tracer)
        fake_openai = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))

        with (
            patch.dict("os.environ", {"DEEPSEEK_API_KEY": "test-key"}),
            patch("openai.OpenAI", return_value=fake_openai),
            patch.object(
                chat_service_module, "execute_tool", return_value={"jobs": [], "total": 0}
            ),
        ):
            gen = service.stream_response("sess-2", "有 python 工作吗")
            next(gen)  # 只消费一个事件即放弃
            gen.close()

        turn_end = [p for k, p in tracer.events if k == "turn_end"]
        self.assertEqual(len(turn_end), 1)
        self.assertEqual(turn_end[0]["error"], "interrupted")


if __name__ == "__main__":
    unittest.main()
