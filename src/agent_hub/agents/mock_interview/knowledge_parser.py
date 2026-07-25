"""多格式知识库解析器。

支持的格式：
- Markdown (.md): 按 ## 标题切分
- PDF (.pdf): 使用 pypdf 提取文本，按 1000 字切分
- JSON (.json): 期望 [{question, answer, tags}] 格式
- TXT (.txt): 按 1000 字切分
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import BinaryIO


@dataclass
class ParsedChunk:
    """解析后的知识块"""

    title: str
    content: str
    metadata: dict


def parse_markdown(content: str, filename: str) -> list[ParsedChunk]:
    """按 ## 标题切分 Markdown 文档。"""
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

    return chunks


def parse_pdf(file: BinaryIO, filename: str) -> list[ParsedChunk]:
    """使用 pypdf 提取 PDF 文本，按 1000 字切分。"""
    try:
        from pypdf import PdfReader
    except ImportError:
        raise ImportError("pypdf is required for PDF parsing. Install with: pip install pypdf")

    reader = PdfReader(file)
    full_text = ""
    for page in reader.pages:
        text = page.extract_text()
        if text:
            full_text += text + "\n"

    return _split_by_length(full_text, filename, chunk_size=1000)


def parse_json(content: str, filename: str) -> list[ParsedChunk]:
    """解析 JSON 格式，期望 [{question, answer, tags}] 格式。"""
    data = json.loads(content)

    if not isinstance(data, list):
        raise ValueError("JSON must be an array of objects")

    chunks: list[ParsedChunk] = []
    for idx, item in enumerate(data):
        if not isinstance(item, dict):
            continue

        question = item.get("question", "")
        answer = item.get("answer", "")
        tags = item.get("tags", [])
        difficulty = item.get("difficulty", "medium")

        if question or answer:
            title = question[:100] if question else f"Item {idx + 1}"
            content = (
                f"Q: {question}\n\nA: {answer}" if question and answer else (answer or question)
            )
            chunks.append(
                ParsedChunk(
                    title=title,
                    content=content,
                    metadata={
                        "tags": tags,
                        "difficulty": difficulty,
                        "index": idx,
                    },
                )
            )

    return chunks


def parse_txt(content: str, filename: str) -> list[ParsedChunk]:
    """按 1000 字切分 TXT 文件。"""
    return _split_by_length(content, filename, chunk_size=1000)


def _split_by_length(text: str, filename: str, chunk_size: int = 1000) -> list[ParsedChunk]:
    """按字符长度切分文本。"""
    chunks: list[ParsedChunk] = []
    text = text.strip()
    if not text:
        return chunks

    parts = []
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

    return chunks


def parse_file(
    file: BinaryIO | None,
    content: str | None,
    filename: str,
    format_hint: str | None = None,
) -> list[ParsedChunk]:
    """统一入口：根据文件名或格式提示选择解析器。"""
    fmt = format_hint or _detect_format(filename)

    if fmt == "pdf":
        if file is None:
            raise ValueError("PDF parsing requires a file object")
        return parse_pdf(file, filename)
    elif fmt == "markdown":
        if content is None:
            raise ValueError("Markdown parsing requires content string")
        return parse_markdown(content, filename)
    elif fmt == "json":
        if content is None:
            raise ValueError("JSON parsing requires content string")
        return parse_json(content, filename)
    elif fmt == "txt":
        if content is None:
            raise ValueError("TXT parsing requires content string")
        return parse_txt(content, filename)
    else:
        raise ValueError(f"Unsupported format: {fmt}")


def _detect_format(filename: str) -> str:
    """根据文件扩展名检测格式。"""
    lower = filename.lower()
    if lower.endswith(".md") or lower.endswith(".markdown"):
        return "markdown"
    elif lower.endswith(".pdf"):
        return "pdf"
    elif lower.endswith(".json"):
        return "json"
    elif lower.endswith(".txt"):
        return "txt"
    else:
        return "txt"  # 默认当作纯文本处理
