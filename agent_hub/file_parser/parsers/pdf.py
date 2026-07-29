"""PDF 解析器。"""

from __future__ import annotations

import io

from .base import BaseParser, ParsedChunk, ParseResult


class PdfParser(BaseParser):
    """PDF 解析器，使用 pypdf 提取文本"""

    def parse(self, file_bytes: bytes, filename: str) -> ParseResult:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(file_bytes))
        total_pages = len(reader.pages)

        # 限制页数
        max_pages = min(total_pages, self.config.max_pdf_pages)
        pages_text: list[str] = []

        for i, page in enumerate(reader.pages[:max_pages]):
            text = page.extract_text() or ""
            pages_text.append(text)

        full_text = "\n\n".join(pages_text)
        full_text = self._truncate_text(full_text)

        chunks = self._create_chunks(pages_text, filename)

        metadata = {
            "format": "pdf",
            "size_bytes": len(file_bytes),
            "total_pages": total_pages,
            "parsed_pages": max_pages,
            "char_count": len(full_text),
        }

        if total_pages > max_pages:
            metadata["truncated"] = True
            metadata["truncated_pages"] = total_pages - max_pages

        return ParseResult(
            text=full_text,
            chunks=chunks,
            metadata=metadata,
        )

    def _create_chunks(self, pages_text: list[str], filename: str) -> list[ParsedChunk]:
        """每页作为一个 chunk"""
        chunks: list[ParsedChunk] = []

        for i, text in enumerate(pages_text):
            text = text.strip()
            if not text:
                continue

            chunks.append(
                ParsedChunk(
                    title=f"{filename} - Page {i + 1}",
                    content=text,
                    metadata={"page": i + 1},
                )
            )

            if len(chunks) >= self.config.max_chunks:
                break

        return chunks
