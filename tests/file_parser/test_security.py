"""安全验证测试。"""

import unittest

from agent_hub.file_parser.config import ParserConfig
from agent_hub.file_parser.security import (
    FileTooLargeError,
    MimeTypeMismatchError,
    UnsupportedFormatError,
    detect_mime_by_magic,
    get_mime_from_extension,
    validate_file,
)


class TestMimeDetection(unittest.TestCase):
    """MIME 类型检测测试"""

    def test_get_mime_from_extension_txt(self):
        self.assertEqual(get_mime_from_extension("test.txt"), "text/plain")

    def test_get_mime_from_extension_pdf(self):
        self.assertEqual(get_mime_from_extension("document.pdf"), "application/pdf")

    def test_get_mime_from_extension_docx(self):
        self.assertEqual(
            get_mime_from_extension("document.docx"),
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )

    def test_get_mime_from_extension_unknown(self):
        self.assertIsNone(get_mime_from_extension("file.xyz"))

    def test_get_mime_from_extension_case_insensitive(self):
        self.assertEqual(get_mime_from_extension("TEST.PDF"), "application/pdf")
        self.assertEqual(get_mime_from_extension("doc.DOCX"),
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document")

    def test_detect_pdf_magic(self):
        pdf_header = b"%PDF-1.4\n"
        self.assertEqual(detect_mime_by_magic(pdf_header), "application/pdf")

    def test_detect_zip_magic(self):
        zip_header = b"PK\x03\x04" + b"\x00" * 20
        self.assertEqual(detect_mime_by_magic(zip_header), "application/zip")

    def test_detect_png_magic(self):
        png_header = b"\x89PNG\r\n\x1a\n" + b"\x00" * 20
        self.assertEqual(detect_mime_by_magic(png_header), "image/png")

    def test_detect_jpeg_magic(self):
        jpeg_header = b"\xff\xd8\xff\xe0" + b"\x00" * 20
        self.assertEqual(detect_mime_by_magic(jpeg_header), "image/jpeg")

    def test_detect_gzip_magic(self):
        gzip_header = b"\x1f\x8b\x08" + b"\x00" * 20
        self.assertEqual(detect_mime_by_magic(gzip_header), "application/gzip")


class TestFileValidation(unittest.TestCase):
    """文件验证测试"""

    def setUp(self):
        self.config = ParserConfig()

    def test_validate_text_file(self):
        content = b"Hello, World!"
        info = validate_file(content, "test.txt", self.config)
        self.assertEqual(info.mime_type, "text/plain")
        self.assertEqual(info.parser_name, "text")
        self.assertEqual(info.size_bytes, len(content))

    def test_validate_json_file(self):
        content = b'{"key": "value"}'
        info = validate_file(content, "data.json", self.config)
        self.assertEqual(info.mime_type, "application/json")
        self.assertEqual(info.parser_name, "json")

    def test_validate_markdown_file(self):
        content = b"# Title\n\nSome content"
        info = validate_file(content, "README.md", self.config)
        self.assertEqual(info.mime_type, "text/markdown")
        self.assertEqual(info.parser_name, "markdown")

    def test_validate_pdf_file(self):
        # 模拟 PDF 文件头
        content = b"%PDF-1.4\n" + b"\x00" * 100
        info = validate_file(content, "document.pdf", self.config)
        self.assertEqual(info.mime_type, "application/pdf")
        self.assertEqual(info.parser_name, "pdf")

    def test_reject_unsupported_extension(self):
        content = b"some content"
        with self.assertRaises(UnsupportedFormatError) as ctx:
            validate_file(content, "file.exe", self.config)
        self.assertEqual(ctx.exception.code, "UNSUPPORTED_FORMAT")

    def test_reject_file_too_large(self):
        # 创建超过格式限制的文件（.txt 限制为 10MB）
        content = b"x" * (11 * 1024 * 1024)  # 11MB
        with self.assertRaises(FileTooLargeError) as ctx:
            validate_file(content, "large.txt", self.config)
        self.assertEqual(ctx.exception.code, "FILE_TOO_LARGE")

    def test_reject_mime_mismatch(self):
        # PDF 扩展名但实际是 PNG
        png_content = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
        with self.assertRaises(MimeTypeMismatchError) as ctx:
            validate_file(png_content, "fake.pdf", self.config)
        self.assertEqual(ctx.exception.code, "MIME_TYPE_MISMATCH")

    def test_accept_docx_as_zip(self):
        # DOCX 文件本质是 ZIP，应该被正确识别
        # 这里用简化的 ZIP 头模拟
        zip_header = b"PK\x03\x04" + b"\x00" * 100
        # 对于 DOCX，我们允许它被检测为 ZIP 格式
        # 实际的 DOCX 验证会在 _detect_office_type 中处理


class TestConfigLimits(unittest.TestCase):
    """配置限制测试"""

    def test_default_config(self):
        config = ParserConfig()
        self.assertEqual(config.max_file_size_mb, 10)
        self.assertEqual(config.max_pdf_pages, 100)
        self.assertEqual(config.max_archive_ratio, 10)

    def test_custom_config(self):
        config = ParserConfig(
            max_file_size_mb=5,
            max_pdf_pages=50,
            max_archive_ratio=5,
        )
        self.assertEqual(config.max_file_size_mb, 5)
        self.assertEqual(config.max_file_size_bytes, 5 * 1024 * 1024)

    def test_config_immutable(self):
        config = ParserConfig()
        with self.assertRaises(AttributeError):
            config.max_file_size_mb = 20


if __name__ == "__main__":
    unittest.main()
