"""召回评测纯函数单测（不依赖 PG / 网络）。"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from eval_recall import keyword_rank, mrr, recall_at_k  # noqa: E402


class KeywordRankTest(unittest.TestCase):
    JOBS = [
        {
            "id": "j1",
            "title_original": "Python Backend",
            "description_original": "FastAPI services",
            "skills": ["Python"],
        },
        {
            "id": "j2",
            "title_original": "Designer",
            "description_original": "Figma mockups",
            "skills": ["Figma"],
        },
        {
            "id": "j3",
            "title_original": "Fullstack",
            "description_original": "Python and React",
            "skills": ["Python", "React"],
        },
    ]

    def test_ranks_by_hit_count_desc(self):
        cand = {"skills": ["Python", "React"], "desired_roles": []}
        self.assertEqual(keyword_rank(cand, self.JOBS), ["j3", "j1"])

    def test_zero_hit_jobs_excluded(self):
        cand = {"skills": ["Rust"], "desired_roles": []}
        self.assertEqual(keyword_rank(cand, self.JOBS), [])

    def test_case_insensitive_and_dict_skills(self):
        cand = {"skills": [{"name": "python"}], "desired_roles": ["designer"]}
        ranked = keyword_rank(cand, self.JOBS)
        self.assertIn("j1", ranked)
        self.assertIn("j2", ranked)


class MetricsTest(unittest.TestCase):
    def test_recall_at_k(self):
        self.assertEqual(recall_at_k(["a", "b", "c"], {"a", "c"}, 2), 0.5)
        self.assertEqual(recall_at_k(["a", "b", "c"], {"a", "c"}, 3), 1.0)
        self.assertEqual(recall_at_k([], {"a"}, 5), 0.0)
        self.assertEqual(recall_at_k(["a"], set(), 5), 0.0)

    def test_mrr(self):
        self.assertEqual(mrr(["x", "a"], {"a"}), 0.5)
        self.assertEqual(mrr(["a"], {"a"}), 1.0)
        self.assertEqual(mrr(["x", "y"], {"a"}), 0.0)


class ParaphrasePurityTest(unittest.TestCase):
    """锁定改写子集纯度：整条词条匹配下，改写候选人的关键词召回不得命中其 qrels 相关职位。

    若未来把 keyword_rank 改成分词匹配，此测试会失败，防止悄悄重新引入泄漏。
    """

    def test_paraphrase_candidates_have_zero_keyword_hits_on_relevant_jobs(self):
        import json

        dataset = json.loads(
            (Path(__file__).resolve().parent.parent / "scripts" / "eval_dataset.json").read_text(
                encoding="utf-8"
            )
        )
        jobs_by_id = {job["id"]: job for job in dataset["jobs"]}
        candidates = {c["id"]: c for c in dataset["candidates"]}
        for cand_id in dataset["paraphrase_candidates"]:
            ranked = keyword_rank(candidates[cand_id], list(jobs_by_id.values()))
            relevant = set(dataset["qrels"][cand_id])
            self.assertEqual(
                set(ranked) & relevant,
                set(),
                f"{cand_id} 的关键词召回命中了相关职位——改写子集纯度被破坏",
            )


if __name__ == "__main__":
    unittest.main()
