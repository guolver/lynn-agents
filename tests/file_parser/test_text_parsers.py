"""文本解析器测试：TXT、Markdown、JSON。"""

import json
import unittest

from agent_hub.file_parser.config import ParserConfig
from agent_hub.file_parser.parsers.text import JsonParser, MarkdownParser, TextParser


class TestTextParser(unittest.TestCase):
    """纯文本解析器测试"""

    def setUp(self):
        self.config = ParserConfig()
        self.parser = TextParser(self.config)

    def test_parse_simple_text(self):
        content = b"Hello, World!"
        result = self.parser.parse(content, "test.txt")

        self.assertEqual(result.text, "Hello, World!")
        self.assertEqual(result.metadata["format"], "text")
        self.assertEqual(result.metadata["size_bytes"], len(content))

    def test_parse_utf8_text(self):
        content = "你好，世界！".encode("utf-8")
        result = self.parser.parse(content, "chinese.txt")

        self.assertEqual(result.text, "你好，世界！")

    def test_parse_gbk_text(self):
        content = "你好，世界！".encode("gbk")
        result = self.parser.parse(content, "gbk.txt")

        self.assertEqual(result.text, "你好，世界！")

    def test_parse_long_text_creates_chunks(self):
        # 创建超过 chunk_size 的文本
        content = ("This is a test sentence. " * 100).encode("utf-8")
        result = self.parser.parse(content, "long.txt")

        self.assertGreater(len(result.chunks), 1)
        self.assertTrue(all(c.content for c in result.chunks))

    def test_truncate_very_long_text(self):
        config = ParserConfig(max_text_length=100)
        parser = TextParser(config)
        content = ("x" * 200).encode("utf-8")
        result = parser.parse(content, "huge.txt")

        self.assertTrue(result.text.endswith("[Content truncated...]"))
        self.assertLessEqual(len(result.text), 150)  # 100 + truncation message


class TestMarkdownParser(unittest.TestCase):
    """Markdown 解析器测试"""

    def setUp(self):
        self.config = ParserConfig()
        self.parser = MarkdownParser(self.config)

    def test_parse_simple_markdown(self):
        content = b"# Title\n\nSome content here."
        result = self.parser.parse(content, "README.md")

        self.assertIn("Title", result.text)
        self.assertEqual(result.metadata["format"], "markdown")

    def test_parse_markdown_with_sections(self):
        content = b"""# Main Title

Introduction paragraph.

## Section 1

Content for section 1.

## Section 2

Content for section 2.
"""
        result = self.parser.parse(content, "doc.md")

        # 应该按 ## 切分成多个 chunks
        self.assertGreaterEqual(len(result.chunks), 2)

        # 检查 chunk 标题
        titles = [c.title for c in result.chunks]
        self.assertIn("Section 1", titles)
        self.assertIn("Section 2", titles)

    def test_parse_markdown_without_headers(self):
        content = b"Just some plain text without headers."
        result = self.parser.parse(content, "plain.md")

        self.assertEqual(len(result.chunks), 1)
        self.assertEqual(result.chunks[0].title, "plain.md")


class TestJsonParser(unittest.TestCase):
    """JSON 解析器测试"""

    def setUp(self):
        self.config = ParserConfig()
        self.parser = JsonParser(self.config)

    def test_parse_simple_json(self):
        data = {"key": "value", "number": 42}
        content = json.dumps(data).encode("utf-8")
        result = self.parser.parse(content, "data.json")

        self.assertEqual(result.metadata["format"], "json")
        self.assertEqual(result.metadata["type"], "dict")

    def test_parse_qa_format_json(self):
        data = [
            {"question": "What is Python?", "answer": "A programming language", "tags": ["python"]},
            {"question": "What is FastAPI?", "answer": "A web framework", "tags": ["fastapi"]},
        ]
        content = json.dumps(data).encode("utf-8")
        result = self.parser.parse(content, "qa.json")

        self.assertEqual(len(result.chunks), 2)
        self.assertIn("What is Python?", result.chunks[0].title)
        self.assertIn("Q:", result.chunks[0].content)
        self.assertIn("A:", result.chunks[0].content)

    def test_parse_nested_json(self):
        data = {"level1": {"level2": {"level3": "value"}}}
        content = json.dumps(data).encode("utf-8")
        result = self.parser.parse(content, "nested.json")

        self.assertEqual(len(result.chunks), 1)

    def test_reject_deeply_nested_json(self):
        # 创建超过深度限制的 JSON
        config = ParserConfig(max_json_depth=5)
        parser = JsonParser(config)

        # 构建深度为 10 的嵌套结构
        data = {"level": None}
        current = data
        for i in range(10):
            current["level"] = {"level": None}
            current = current["level"]

        content = json.dumps(data).encode("utf-8")

        with self.assertRaises(ValueError) as ctx:
            parser.parse(content, "deep.json")
        self.assertIn("depth", str(ctx.exception))

    def test_parse_invalid_json(self):
        content = b"not valid json {"
        with self.assertRaises(json.JSONDecodeError):
            self.parser.parse(content, "invalid.json")


if __name__ == "__main__":
    unittest.main()
