"""文本格式解析器：TXT、Markdown、JSON。"""

from __future__ import annotations

import json
import re
from typing import Any

from .base import BaseParser, ParsedChunk, ParseResult


class TextParser(BaseParser):
    """纯文本解析器"""

    def parse(self, file_bytes: bytes, filename: str) -> ParseResult:
        text = self._decode_text(file_bytes)
        text = self._truncate_text(text)
        chunks = self._split_by_length(text, filename)

        return ParseResult(
            text=text,
            chunks=chunks,
            metadata={
                "format": "text",
                "size_bytes": len(file_bytes),
                "char_count": len(text),
            },
        )

    def _decode_text(self, file_bytes: bytes) -> str:
        """尝试多种编码解码文本"""
        encodings = ["utf-8", "gbk", "gb2312", "latin-1"]
        for encoding in encodings:
            try:
                return file_bytes.decode(encoding)
            except UnicodeDecodeError:
                continue
        # 最后使用 latin-1，它不会失败
        return file_bytes.decode("latin-1")


class MarkdownParser(BaseParser):
    """Markdown 解析器，按标题切分"""

    def parse(self, file_bytes: bytes, filename: str) -> ParseResult:
        text = self._decode_text(file_bytes)
        text = self._truncate_text(text)
        chunks = self._parse_markdown(text, filename)

        return ParseResult(
            text=text,
            chunks=chunks,
            metadata={
                "format": "markdown",
                "size_bytes": len(file_bytes),
                "section_count": len(chunks),
            },
        )

    def _decode_text(self, file_bytes: bytes) -> str:
        try:
            return file_bytes.decode("utf-8")
        except UnicodeDecodeError:
            return file_bytes.decode("latin-1")

    def _parse_markdown(self, content: str, filename: str) -> list[ParsedChunk]:
        """按 ## 标题切分 Markdown 文档"""
        chunks: list[ParsedChunk] = []
        sections = re.split(r"(?=^## )", content, flags=re.MULTILINE)

        for section in sections:
            section = section.strip()
            if not section:
                continue

            lines = section.split("\n", 1)
            if lines[0].startswith("## "):
                title = lines[0][3:].strip()
                body = lines[1].strip() if len(lines) > 1 else ""
            else:
                title = filename
                body = section

            if body:
                chunks.append(
                    ParsedChunk(
                        title=title,
                        content=body,
                        metadata={"source_section": title},
                    )
                )

        if len(chunks) > self.config.max_chunks:
            chunks = chunks[: self.config.max_chunks]

        return chunks


class JsonParser(BaseParser):
    """JSON 解析器"""

    def parse(self, file_bytes: bytes, filename: str) -> ParseResult:
        text = file_bytes.decode("utf-8")
        data = self._safe_json_loads(text)
        chunks = self._extract_chunks(data, filename)
        text_output = self._truncate_text(text)

        return ParseResult(
            text=text_output,
            chunks=chunks,
            metadata={
                "format": "json",
                "size_bytes": len(file_bytes),
                "type": type(data).__name__,
            },
        )

    def _safe_json_loads(self, text: str) -> Any:
        """安全解析 JSON，限制嵌套深度"""
        # Python 默认递归限制已经足够防护极端情况
        # 但我们可以手动检查深度
        data = json.loads(text)
        self._check_depth(data, 0)
        return data

    def _check_depth(self, obj: Any, depth: int) -> None:
        """检查 JSON 嵌套深度"""
        if depth > self.config.max_json_depth:
            raise ValueError(f"JSON nesting exceeds maximum depth of {self.config.max_json_depth}")

        if isinstance(obj, dict):
            for value in obj.values():
                self._check_depth(value, depth + 1)
        elif isinstance(obj, list):
            for item in obj:
                self._check_depth(item, depth + 1)

    def _extract_chunks(self, data: Any, filename: str) -> list[ParsedChunk]:
        """从 JSON 数据提取 chunks"""
        chunks: list[ParsedChunk] = []

        # 如果是 QA 格式的数组
        if isinstance(data, list):
            for idx, item in enumerate(data):
                if not isinstance(item, dict):
                    continue

                question = item.get("question", "")
                answer = item.get("answer", "")
                tags = item.get("tags", [])

                if question or answer:
                    title = question[:100] if question else f"Item {idx + 1}"
                    content = (
                        f"Q: {question}\n\nA: {answer}"
                        if question and answer
                        else (answer or question)
                    )
                    chunks.append(
                        ParsedChunk(
                            title=title,
                            content=content,
                            metadata={"tags": tags, "index": idx},
                        )
                    )

                if len(chunks) >= self.config.max_chunks:
                    break
        else:
            # 其他格式，整体作为一个 chunk
            chunks.append(
                ParsedChunk(
                    title=filename,
                    content=json.dumps(data, ensure_ascii=False, indent=2),
                    metadata={},
                )
            )

        return chunks
