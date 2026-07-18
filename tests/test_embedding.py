"""SiliconFlow embedding 模块单元测试（mock OpenAI client，不发真实请求）。"""

import unittest
from unittest.mock import MagicMock, patch

from agent_hub.agents.global_part_time import embedding
from agent_hub.agents.global_part_time.embedding import build_candidate_text


class _FakeItem:
    def __init__(self, vec):
        self.embedding = vec


def _fake_response(vectors):
    return MagicMock(data=[_FakeItem(v) for v in vectors])


class GetEmbeddingsTest(unittest.TestCase):
    def test_returns_none_list_without_api_key(self):
        with patch.object(embedding, "SILICONFLOW_API_KEY", ""):
            self.assertEqual(embedding.get_embeddings(["a", "b"]), [None, None])

    def test_batch_maps_vectors_and_preserves_blanks(self):
        client = MagicMock()
        client.embeddings.create.return_value = _fake_response([[0.1] * 3, [0.2] * 3])
        with (
            patch.object(embedding, "SILICONFLOW_API_KEY", "sk-test"),
            patch.object(embedding, "_get_client", return_value=client),
        ):
            result = embedding.get_embeddings(["hello", "  ", "world"])
        self.assertEqual(result, [[0.1] * 3, None, [0.2] * 3])
        client.embeddings.create.assert_called_once_with(
            model=embedding.EMBEDDING_MODEL, input=["hello", "world"]
        )

    def test_api_error_degrades_to_none(self):
        client = MagicMock()
        client.embeddings.create.side_effect = RuntimeError("boom")
        with (
            patch.object(embedding, "SILICONFLOW_API_KEY", "sk-test"),
            patch.object(embedding, "_get_client", return_value=client),
        ):
            self.assertEqual(embedding.get_embeddings(["hello"]), [None])

    def test_get_embedding_single(self):
        client = MagicMock()
        client.embeddings.create.return_value = _fake_response([[1.0, 0.0]])
        with (
            patch.object(embedding, "SILICONFLOW_API_KEY", "sk-test"),
            patch.object(embedding, "_get_client", return_value=client),
        ):
            self.assertEqual(embedding.get_embedding("hi"), [1.0, 0.0])

    def test_empty_input_returns_empty_list(self):
        with patch.object(embedding, "SILICONFLOW_API_KEY", "sk-test"):
            self.assertEqual(embedding.get_embeddings([]), [])

    def test_all_blank_inputs_skip_api_call(self):
        client = MagicMock()
        with (
            patch.object(embedding, "SILICONFLOW_API_KEY", "sk-test"),
            patch.object(embedding, "_get_client", return_value=client),
        ):
            result = embedding.get_embeddings(["", "   "])
        self.assertEqual(result, [None, None])
        client.embeddings.create.assert_not_called()

    def test_mismatched_vector_count_degrades_to_none(self):
        client = MagicMock()
        client.embeddings.create.return_value = _fake_response([[0.1] * 3])
        with (
            patch.object(embedding, "SILICONFLOW_API_KEY", "sk-test"),
            patch.object(embedding, "_get_client", return_value=client),
        ):
            result = embedding.get_embeddings(["hello", "world"])
        self.assertEqual(result, [None, None])


class BuildCandidateTextTests(unittest.TestCase):
    def test_includes_resume_summary(self):
        text = build_candidate_text(
            {
                "skills": [{"name": "python"}],
                "desired_roles": ["backend"],
                "resume_summary": "五年后端开发经验，主导支付系统重构",
            }
        )
        self.assertIn("Skills: python", text)
        self.assertIn("Desired roles: backend", text)
        self.assertIn("Experience: 五年后端开发经验，主导支付系统重构", text)

    def test_without_resume_summary_unchanged(self):
        text = build_candidate_text({"skills": ["python"]})
        self.assertEqual(text, "Skills: python")

    def test_resume_summary_truncated_to_1500(self):
        text = build_candidate_text({"resume_summary": "x" * 2000})
        self.assertEqual(text, "Experience: " + "x" * 1500)

    def test_blank_resume_summary_ignored(self):
        text = build_candidate_text({"skills": ["python"], "resume_summary": "   "})
        self.assertEqual(text, "Skills: python")


if __name__ == "__main__":
    unittest.main()
