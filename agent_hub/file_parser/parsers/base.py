"""解析器基类。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from ..config import ParserConfig


@dataclass
class ParsedChunk:
    """解析后的文本块"""

    title: str
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ParseResult:
    """解析结果"""

    text: str
    chunks: list[ParsedChunk]
    metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "chunks": [
                {
                    "title": c.title,
                    "content": c.content,
                    "metadata": c.metadata,
                }
                for c in self.chunks
            ],
            "metadata": self.metadata,
        }


class BaseParser(ABC):
    """解析器基类"""

    def __init__(self, config: ParserConfig):
        self.config = config

    @abstractmethod
    def parse(self, file_bytes: bytes, filename: str) -> ParseResult:
        """
        解析文件内容。

        Args:
            file_bytes: 文件二进制内容
            filename: 原始文件名

        Returns:
            ParseResult: 解析结果
        """
        pass

    def _truncate_text(self, text: str) -> str:
        """截断过长的文本"""
        if len(text) > self.config.max_text_length:
            return text[: self.config.max_text_length] + "\n\n[Content truncated...]"
        return text

    def _split_by_length(
        self,
        text: str,
        filename: str,
        chunk_size: int = 1000,
    ) -> list[ParsedChunk]:
        """按字符长度切分文本"""
        chunks: list[ParsedChunk] = []
        text = text.strip()
        if not text:
            return chunks

        parts: list[str] = []
        current_pos = 0
        while current_pos < len(text):
            end_pos = min(current_pos + chunk_size, len(text))
            # 尝试在句号、问号、感叹号或换行处切分
            if end_pos < len(text):
                for sep in ["\n\n", "。", ".", "？", "?", "！", "!", "\n"]:
                    last_sep = text.rfind(sep, current_pos, end_pos)
                    if last_sep > current_pos:
                        end_pos = last_sep + len(sep)
                        break
            parts.append(text[current_pos:end_pos].strip())
            current_pos = end_pos

        for idx, part in enumerate(parts):
            if part:
                chunks.append(
                    ParsedChunk(
                        title=f"{filename} (Part {idx + 1})",
                        content=part,
                        metadata={"chunk_index": idx, "total_chunks": len(parts)},
                    )
                )

        # 限制 chunk 数量
        if len(chunks) > self.config.max_chunks:
            chunks = chunks[: self.config.max_chunks]
            chunks[-1].metadata["truncated"] = True

        return chunks
