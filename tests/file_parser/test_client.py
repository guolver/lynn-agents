"""FileParserClient 测试。"""

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent_hub.core.file_parser_client import (
    FileParserClient,
    FileParserError,
    ParseResult,
    parse_file,
)


class TestParseResult(unittest.TestCase):
    """ParseResult 数据类测试"""

    def test_from_dict(self):
        data = {
            "text": "Hello, World!",
            "chunks": [
                {"title": "Title", "content": "Content", "metadata": {"key": "value"}}
            ],
            "metadata": {"format": "text"},
        }
        result = ParseResult.from_dict(data)

        self.assertEqual(result.text, "Hello, World!")
        self.assertEqual(len(result.chunks), 1)
        self.assertEqual(result.chunks[0].title, "Title")
        self.assertEqual(result.chunks[0].content, "Content")
        self.assertEqual(result.chunks[0].metadata["key"], "value")
        self.assertEqual(result.metadata["format"], "text")

    def test_from_dict_empty_chunks(self):
        data = {
            "text": "Hello",
            "chunks": [],
            "metadata": {},
        }
        result = ParseResult.from_dict(data)

        self.assertEqual(result.text, "Hello")
        self.assertEqual(len(result.chunks), 0)

    def test_from_dict_missing_optional_fields(self):
        data = {
            "text": "Hello",
        }
        result = ParseResult.from_dict(data)

        self.assertEqual(result.text, "Hello")
        self.assertEqual(len(result.chunks), 0)
        self.assertEqual(result.metadata, {})


class TestFileParserError(unittest.TestCase):
    """FileParserError 测试"""

    def test_error_attributes(self):
        error = FileParserError("TEST_CODE", "Test message")

        self.assertEqual(error.code, "TEST_CODE")
        self.assertEqual(error.message, "Test message")
        self.assertIn("TEST_CODE", str(error))
        self.assertIn("Test message", str(error))


@pytest.mark.asyncio
class TestFileParserClient:
    """FileParserClient 异步测试"""

    async def test_parse_success(self):
        """测试成功解析"""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "success": True,
            "data": {
                "text": "Hello, World!",
                "chunks": [],
                "metadata": {"format": "text"},
            },
        }

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_client.is_closed = False
            mock_client_class.return_value = mock_client

            client = FileParserClient(base_url="http://test:8001")
            client._client = mock_client

            result = await client.parse(b"Hello, World!", "test.txt")

            assert result.text == "Hello, World!"
            assert result.metadata["format"] == "text"

    async def test_parse_error(self):
        """测试解析错误"""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "success": False,
            "error": {
                "code": "UNSUPPORTED_FORMAT",
                "message": "Unsupported file format",
            },
        }

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_client.is_closed = False
            mock_client_class.return_value = mock_client

            client = FileParserClient(base_url="http://test:8001")
            client._client = mock_client

            with pytest.raises(FileParserError) as exc_info:
                await client.parse(b"content", "test.exe")

            assert exc_info.value.code == "UNSUPPORTED_FORMAT"

    async def test_health_check_success(self):
        """测试健康检查成功"""
        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_client.is_closed = False
            mock_client_class.return_value = mock_client

            client = FileParserClient(base_url="http://test:8001")
            client._client = mock_client

            is_healthy = await client.health()
            assert is_healthy is True

    async def test_health_check_failure(self):
        """测试健康检查失败"""
        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.get.side_effect = Exception("Connection refused")
            mock_client.is_closed = False
            mock_client_class.return_value = mock_client

            client = FileParserClient(base_url="http://test:8001")
            client._client = mock_client

            is_healthy = await client.health()
            assert is_healthy is False

    async def test_context_manager(self):
        """测试上下文管理器"""
        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.is_closed = False
            mock_client_class.return_value = mock_client

            async with FileParserClient(base_url="http://test:8001") as client:
                client._client = mock_client
                pass

            mock_client.aclose.assert_called_once()

    async def test_get_formats(self):
        """测试获取格式列表"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "formats": [
                {"extension": ".pdf", "mime_type": "application/pdf", "max_size_mb": 10},
                {"extension": ".txt", "mime_type": "text/plain", "max_size_mb": 10},
            ]
        }

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_client.is_closed = False
            mock_client_class.return_value = mock_client

            client = FileParserClient(base_url="http://test:8001")
            client._client = mock_client

            formats = await client.get_formats()

            assert len(formats) == 2
            assert formats[0]["extension"] == ".pdf"


class TestClientConfiguration(unittest.TestCase):
    """客户端配置测试"""

    def test_default_url(self):
        client = FileParserClient()
        self.assertEqual(client.base_url, "http://file-parser:8001")

    def test_custom_url(self):
        client = FileParserClient(base_url="http://custom:9000")
        self.assertEqual(client.base_url, "http://custom:9000")

    def test_default_timeout(self):
        client = FileParserClient()
        self.assertEqual(client.timeout, 35.0)

    def test_custom_timeout(self):
        client = FileParserClient(timeout=60.0)
        self.assertEqual(client.timeout, 60.0)

    @patch.dict("os.environ", {"FILE_PARSER_URL": "http://env-url:8001"})
    def test_url_from_environment(self):
        client = FileParserClient()
        self.assertEqual(client.base_url, "http://env-url:8001")


if __name__ == "__main__":
    unittest.main()
