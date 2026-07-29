"""PDF 解析器测试。"""

import io
import unittest

from agent_hub.file_parser.config import ParserConfig
from agent_hub.file_parser.parsers.pdf import PdfParser


class TestPdfParser(unittest.TestCase):
    """PDF 解析器测试"""

    def setUp(self):
        self.config = ParserConfig()
        self.parser = PdfParser(self.config)

    def test_parse_simple_pdf(self):
        """测试解析简单的 PDF"""
        # 创建一个最小的有效 PDF
        pdf_content = self._create_minimal_pdf("Hello, World!")
        result = self.parser.parse(pdf_content, "test.pdf")

        self.assertEqual(result.metadata["format"], "pdf")
        self.assertIn("total_pages", result.metadata)

    def test_pdf_page_limit(self):
        """测试页数限制"""
        config = ParserConfig(max_pdf_pages=2)
        parser = PdfParser(config)

        # 创建多页 PDF（使用 pypdf 在内存中创建）
        pdf_content = self._create_multi_page_pdf(5)
        result = parser.parse(pdf_content, "multi.pdf")

        self.assertEqual(result.metadata["total_pages"], 5)
        self.assertEqual(result.metadata["parsed_pages"], 2)
        self.assertTrue(result.metadata.get("truncated", False))

    def test_pdf_chunks_per_page(self):
        """测试每页生成一个 chunk"""
        pdf_content = self._create_multi_page_pdf(3)
        result = self.parser.parse(pdf_content, "pages.pdf")

        # 应该有对应页数的 chunks（可能有些空页被跳过）
        self.assertGreaterEqual(len(result.chunks), 1)
        for chunk in result.chunks:
            self.assertIn("page", chunk.metadata)

    def _create_minimal_pdf(self, text: str) -> bytes:
        """创建包含指定文本的最小 PDF"""
        try:
            from pypdf import PdfWriter
            from reportlab.lib.pagesizes import letter
            from reportlab.pdfgen import canvas
        except ImportError:
            # 如果没有 reportlab，返回一个空 PDF 结构
            return self._create_empty_pdf()

        buffer = io.BytesIO()
        c = canvas.Canvas(buffer, pagesize=letter)
        c.drawString(100, 750, text)
        c.save()
        return buffer.getvalue()

    def _create_multi_page_pdf(self, num_pages: int) -> bytes:
        """创建多页 PDF"""
        try:
            from reportlab.lib.pagesizes import letter
            from reportlab.pdfgen import canvas
        except ImportError:
            return self._create_empty_pdf()

        buffer = io.BytesIO()
        c = canvas.Canvas(buffer, pagesize=letter)
        for i in range(num_pages):
            c.drawString(100, 750, f"Page {i + 1}")
            c.showPage()
        c.save()
        return buffer.getvalue()

    def _create_empty_pdf(self) -> bytes:
        """创建一个最小的有效 PDF 结构"""
        # 最小有效 PDF
        return b"""%PDF-1.4
1 0 obj
<< /Type /Catalog /Pages 2 0 R >>
endobj
2 0 obj
<< /Type /Pages /Kids [3 0 R] /Count 1 >>
endobj
3 0 obj
<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] >>
endobj
xref
0 4
0000000000 65535 f
0000000009 00000 n
0000000058 00000 n
0000000115 00000 n
trailer
<< /Size 4 /Root 1 0 R >>
startxref
196
%%EOF"""


class TestPdfParserEdgeCases(unittest.TestCase):
    """PDF 解析器边界情况测试"""

    def setUp(self):
        self.config = ParserConfig()
        self.parser = PdfParser(self.config)

    def test_empty_pdf(self):
        """测试空 PDF"""
        pdf_content = self._create_empty_pdf()
        result = self.parser.parse(pdf_content, "empty.pdf")

        # 空 PDF 应该不会崩溃
        self.assertEqual(result.metadata["format"], "pdf")

    def test_pdf_with_no_text(self):
        """测试没有文本的 PDF（纯图片 PDF）"""
        pdf_content = self._create_empty_pdf()
        result = self.parser.parse(pdf_content, "image_only.pdf")

        # 应该返回空文本但不崩溃
        self.assertIsInstance(result.text, str)

    def _create_empty_pdf(self) -> bytes:
        return b"""%PDF-1.4
1 0 obj
<< /Type /Catalog /Pages 2 0 R >>
endobj
2 0 obj
<< /Type /Pages /Kids [3 0 R] /Count 1 >>
endobj
3 0 obj
<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] >>
endobj
xref
0 4
0000000000 65535 f
0000000009 00000 n
0000000058 00000 n
0000000115 00000 n
trailer
<< /Size 4 /Root 1 0 R >>
startxref
196
%%EOF"""


if __name__ == "__main__":
    unittest.main()
