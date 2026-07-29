"""HTML 解析器。"""

from __future__ import annotations

import re

from .base import BaseParser, ParsedChunk, ParseResult


class HtmlParser(BaseParser):
    """HTML 解析器，提取纯文本内容"""

    def parse(self, file_bytes: bytes, filename: str) -> ParseResult:
        from bs4 import BeautifulSoup

        html = self._decode_html(file_bytes)

        # 使用 html.parser 而不是 lxml，更安全
        soup = BeautifulSoup(html, "html.parser")

        # 移除脚本和样式
        for element in soup(["script", "style", "meta", "link", "noscript"]):
            element.decompose()

        # 提取标题
        title = ""
        if soup.title:
            title = soup.title.get_text(strip=True)

        # 提取正文
        text = soup.get_text(separator="\n", strip=True)
        text = self._clean_text(text)
        text = self._truncate_text(text)

        chunks = self._extract_sections(soup, filename)

        return ParseResult(
            text=text,
            chunks=chunks,
            metadata={
                "format": "html",
                "size_bytes": len(file_bytes),
                "title": title,
                "char_count": len(text),
            },
        )

    def _decode_html(self, file_bytes: bytes) -> str:
        """解码 HTML，尝试检测编码"""
        # 尝试从 meta 标签检测编码
        try:
            # 先用 latin-1 解码查找 charset
            temp = file_bytes.decode("latin-1")
            charset_match = re.search(r'charset=["\']?([^"\'\s>]+)', temp, re.I)
            if charset_match:
                charset = charset_match.group(1)
                try:
                    return file_bytes.decode(charset)
                except (UnicodeDecodeError, LookupError):
                    pass
        except Exception:
            pass

        # 默认尝试 UTF-8
        try:
            return file_bytes.decode("utf-8")
        except UnicodeDecodeError:
            return file_bytes.decode("latin-1")

    def _clean_text(self, text: str) -> str:
        """清理提取的文本"""
        # 合并多个空行
        text = re.sub(r"\n{3,}", "\n\n", text)
        # 合并多个空格
        text = re.sub(r"[ \t]+", " ", text)
        return text.strip()

    def _extract_sections(self, soup, filename: str) -> list[ParsedChunk]:
        """按标题标签提取章节"""
        from bs4 import BeautifulSoup

        chunks: list[ParsedChunk] = []

        # 查找所有标题
        headings = soup.find_all(["h1", "h2", "h3"])

        if not headings:
            # 没有标题，整体作为一个 chunk
            text = soup.get_text(separator="\n", strip=True)
            if text:
                chunks.append(
                    ParsedChunk(
                        title=filename,
                        content=self._clean_text(text),
                        metadata={},
                    )
                )
            return chunks

        for heading in headings:
            title = heading.get_text(strip=True)

            # 获取标题后的内容直到下一个标题
            content_parts: list[str] = []
            for sibling in heading.find_next_siblings():
                if sibling.name in ["h1", "h2", "h3"]:
                    break
                text = sibling.get_text(strip=True)
                if text:
                    content_parts.append(text)

            if content_parts:
                chunks.append(
                    ParsedChunk(
                        title=title,
                        content="\n".join(content_parts),
                        metadata={"heading_level": heading.name},
                    )
                )

            if len(chunks) >= self.config.max_chunks:
                break

        return chunks
