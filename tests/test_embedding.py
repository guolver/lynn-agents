"""SiliconFlow embedding 模块单元测试（mock OpenAI client，不发真实请求）。"""

import unittest
from unittest.mock import MagicMock, patch

from agent_hub.agents.global_part_time import embedding


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


if __name__ == "__main__":
    unittest.main()
