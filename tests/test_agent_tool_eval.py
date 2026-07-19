"""Agent 工具评测的数据集有效性与打分逻辑单测（不调用 LLM API）。"""

import importlib.util
import unittest
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "eval_agent_tools",
    Path(__file__).resolve().parent.parent / "scripts" / "eval_agent_tools.py",
)
eval_agent_tools = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(eval_agent_tools)


class DatasetValidityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases = eval_agent_tools.load_cases()

    def test_case_ids_unique(self):
        ids = [c["id"] for c in self.cases]
        self.assertEqual(len(ids), len(set(ids)))

    def test_load_cases_rejects_unknown_tools(self):
        import json
        import tempfile

        bad = {"cases": [{"id": "x", "expected_tools": ["not_a_tool"]}]}
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(bad, f)
            path = Path(f.name)
        with self.assertRaises(ValueError):
            eval_agent_tools.load_cases(path)
        path.unlink()

    def test_candidate_placeholder_cases_have_candidate(self):
        for case in self.cases:
            expected = case.get("expected_args") or {}
            if any(v == "$CANDIDATE" for v in expected.values()):
                self.assertTrue(case.get("candidate_id"), f"{case['id']} 缺 candidate_id")

    def test_expected_job_ids_present_in_history(self):
        for case in self.cases:
            job_id = (case.get("expected_args") or {}).get("job_id")
            if job_id:
                history_text = " ".join(m["content"] for m in case.get("history", []))
                self.assertIn(job_id, history_text, f"{case['id']} 的 job_id 未在历史中出现")

    def test_no_tool_cases_expect_only_no_tool(self):
        for case in self.cases:
            if case["category"] == "no_tool":
                self.assertEqual(case["expected_tools"], ["no_tool"], case["id"])


class BuildMessagesTest(unittest.TestCase):
    def test_candidate_id_appended_to_system_prompt(self):
        messages = eval_agent_tools.build_messages({"candidate_id": "cand-1", "user_message": "hi"})
        self.assertIn("当前候选人 ID: cand-1", messages[0]["content"])
        self.assertEqual(messages[-1], {"role": "user", "content": "hi"})

    def test_history_inserted_between_system_and_user(self):
        messages = eval_agent_tools.build_messages(
            {"history": [{"role": "assistant", "content": "早前回答"}], "user_message": "追问"}
        )
        self.assertEqual([m["role"] for m in messages], ["system", "assistant", "user"])


class ScoreSampleTest(unittest.TestCase):
    def test_correct_tool_and_args(self):
        case = {
            "expected_tools": ["run_matches"],
            "candidate_id": "cand-1",
            "expected_args": {"candidate_id": "$CANDIDATE"},
        }
        result = eval_agent_tools.score_sample(case, "run_matches", {"candidate_id": "cand-1"})
        self.assertTrue(result["tool_ok"])
        self.assertTrue(result["args_ok"])

    def test_wrong_tool(self):
        case = {"expected_tools": ["search_jobs"]}
        result = eval_agent_tools.score_sample(case, "run_matches", {})
        self.assertFalse(result["tool_ok"])

    def test_no_tool_expected_and_respected(self):
        case = {"expected_tools": ["no_tool"]}
        result = eval_agent_tools.score_sample(case, "no_tool", {})
        self.assertTrue(result["tool_ok"])

    def test_arg_value_mismatch_reported(self):
        case = {"expected_tools": ["get_job_detail"], "expected_args": {"job_id": "job-a"}}
        result = eval_agent_tools.score_sample(case, "get_job_detail", {"job_id": "job-b"})
        self.assertTrue(result["tool_ok"])
        self.assertFalse(result["args_ok"])
        self.assertIn("job_id", result["problems"][0])

    def test_arg_presence_only_when_expected_none(self):
        case = {"expected_tools": ["parse_resume"], "expected_args": {"pdf_text": None}}
        ok = eval_agent_tools.score_sample(case, "parse_resume", {"pdf_text": "任意内容"})
        missing = eval_agent_tools.score_sample(case, "parse_resume", {})
        self.assertTrue(ok["args_ok"])
        self.assertFalse(missing["args_ok"])

    def test_numeric_args_compared_numerically(self):
        case = {"expected_tools": ["search_jobs"], "expected_args": {"min_pay": 50}}
        result = eval_agent_tools.score_sample(case, "search_jobs", {"min_pay": 50.0})
        self.assertTrue(result["args_ok"])


class SummarizeTest(unittest.TestCase):
    def test_metrics_aggregation(self):
        cases = [
            {"id": "a", "category": "search_jobs", "expected_tools": ["search_jobs"]},
            {"id": "b", "category": "no_tool", "expected_tools": ["no_tool"]},
        ]
        results = {
            "a": [
                {"tool": "search_jobs", "tool_ok": True, "args_ok": None, "problems": []},
                {"tool": "run_matches", "tool_ok": False, "args_ok": None, "problems": []},
            ],
            "b": [
                {"tool": "no_tool", "tool_ok": True, "args_ok": None, "problems": []},
                {"tool": "search_jobs", "tool_ok": False, "args_ok": None, "problems": []},
            ],
        }
        summary = eval_agent_tools.summarize(cases, results)
        self.assertEqual(summary["total_samples"], 4)
        self.assertAlmostEqual(summary["tool_accuracy"], 0.5)
        self.assertAlmostEqual(summary["false_call_rate"], 0.5)
        self.assertEqual(sorted(summary["unstable_cases"]), ["a", "b"])


if __name__ == "__main__":
    unittest.main()
