"""Pytest fixtures for file parser tests."""

import gzip
import io
import json
import tarfile
import zipfile

import pytest

from agent_hub.file_parser.config import ParserConfig


@pytest.fixture
def parser_config():
    """默认解析器配置"""
    return ParserConfig()


@pytest.fixture
def strict_config():
    """严格限制的配置（用于测试限制）"""
    return ParserConfig(
        max_file_size_mb=1,
        max_pdf_pages=5,
        max_archive_files=10,
        max_archive_ratio=5,
        max_json_depth=10,
        max_text_length=1000,
    )


@pytest.fixture
def sample_text_file():
    """示例文本文件"""
    return b"Hello, World! This is a sample text file."


@pytest.fixture
def sample_json_file():
    """示例 JSON 文件"""
    data = {
        "name": "Test",
        "items": [1, 2, 3],
        "nested": {"key": "value"},
    }
    return json.dumps(data).encode("utf-8")


@pytest.fixture
def sample_qa_json():
    """示例 QA 格式 JSON"""
    data = [
        {"question": "What is Python?", "answer": "A programming language", "tags": ["python"]},
        {"question": "What is FastAPI?", "answer": "A web framework", "tags": ["web"]},
    ]
    return json.dumps(data).encode("utf-8")


@pytest.fixture
def sample_markdown():
    """示例 Markdown 文件"""
    return b"""# Main Title

Introduction paragraph.

## Section 1

Content for section 1.

## Section 2

Content for section 2.
"""


@pytest.fixture
def sample_html():
    """示例 HTML 文件"""
    return b"""<!DOCTYPE html>
<html>
<head>
    <title>Test Page</title>
</head>
<body>
    <h1>Welcome</h1>
    <p>This is a test page.</p>
    <h2>Section 1</h2>
    <p>Content for section 1.</p>
</body>
</html>
"""


@pytest.fixture
def sample_zip():
    """示例 ZIP 文件"""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("file1.txt", "Content of file 1")
        zf.writestr("file2.txt", "Content of file 2")
        zf.writestr("data.json", '{"key": "value"}')
    return buffer.getvalue()


@pytest.fixture
def sample_tar():
    """示例 TAR 文件"""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as tf:
        for i in range(3):
            content = f"Content of file {i}".encode("utf-8")
            info = tarfile.TarInfo(name=f"file{i}.txt")
            info.size = len(content)
            tf.addfile(info, io.BytesIO(content))
    return buffer.getvalue()


@pytest.fixture
def sample_gzip():
    """示例 GZIP 文件"""
    content = b"This is compressed content. " * 10
    return gzip.compress(content)


@pytest.fixture
def zip_bomb_candidate():
    """
    创建高压缩比的 ZIP 用于测试 zip 炸弹检测。
    注意：这不是真正的 zip 炸弹，只是压缩比较高的正常文件。
    """
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        # 重复字符压缩效果很好
        content = "A" * (100 * 1024)  # 100KB 的 A
        zf.writestr("large.txt", content)
    return buffer.getvalue()


@pytest.fixture
def nested_json():
    """深度嵌套的 JSON"""
    def build_nested(depth):
        if depth == 0:
            return "leaf"
        return {"level": build_nested(depth - 1)}

    data = build_nested(20)
    return json.dumps(data).encode("utf-8")


@pytest.fixture
def malicious_html():
    """包含脚本的 HTML（用于测试 XSS 过滤）"""
    return b"""
    <html>
    <body>
        <p>Safe content</p>
        <script>alert('XSS')</script>
        <img src="x" onerror="alert('XSS')">
        <a href="javascript:alert('XSS')">Click me</a>
        <p>More safe content</p>
    </body>
    </html>
    """


@pytest.fixture
def chinese_text():
    """中文文本（UTF-8）"""
    return "你好，世界！这是一段中文测试文本。".encode("utf-8")


@pytest.fixture
def chinese_text_gbk():
    """中文文本（GBK）"""
    return "你好，世界！这是一段中文测试文本。".encode("gbk")
