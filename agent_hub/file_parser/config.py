"""文件解析沙箱配置。

所有安全限制参数集中管理，便于调整和审计。
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class ParserConfig:
    """解析器配置"""

    # 文件大小限制 (MB)
    max_file_size_mb: int = 10
    max_archive_size_mb: int = 50

    # PDF 限制
    max_pdf_pages: int = 100

    # 压缩包限制
    max_archive_files: int = 100
    max_archive_ratio: int = 10  # 压缩比限制（防 zip 炸弹）

    # XML/JSON 限制（防炸弹攻击）
    max_xml_depth: int = 20
    max_json_depth: int = 50

    # 图片限制
    max_image_pixels: int = 50_000_000  # 50 megapixels

    # 解析超时 (秒)
    parse_timeout_seconds: int = 30

    # 文本输出限制
    max_text_length: int = 500_000  # 50 万字符
    max_chunks: int = 500

    # 安全开关
    disable_office_macros: bool = True
    disable_pdf_javascript: bool = True
    disable_html_scripts: bool = True

    @property
    def max_file_size_bytes(self) -> int:
        return self.max_file_size_mb * 1024 * 1024

    @property
    def max_archive_size_bytes(self) -> int:
        return self.max_archive_size_mb * 1024 * 1024


def get_config() -> ParserConfig:
    """从环境变量加载配置，支持覆盖默认值"""
    return ParserConfig(
        max_file_size_mb=int(os.getenv("PARSER_MAX_FILE_SIZE_MB", "10")),
        max_archive_size_mb=int(os.getenv("PARSER_MAX_ARCHIVE_SIZE_MB", "50")),
        max_pdf_pages=int(os.getenv("PARSER_MAX_PDF_PAGES", "100")),
        max_archive_files=int(os.getenv("PARSER_MAX_ARCHIVE_FILES", "100")),
        max_archive_ratio=int(os.getenv("PARSER_MAX_ARCHIVE_RATIO", "10")),
        parse_timeout_seconds=int(os.getenv("PARSER_TIMEOUT_SECONDS", "30")),
    )


# 支持的 MIME 类型及其扩展名映射
SUPPORTED_FORMATS: dict[str, dict] = {
    # 文本格式
    "text/plain": {
        "extensions": [".txt"],
        "max_size_mb": 10,
        "parser": "text",
    },
    "text/markdown": {
        "extensions": [".md", ".markdown"],
        "max_size_mb": 10,
        "parser": "markdown",
    },
    "application/json": {
        "extensions": [".json"],
        "max_size_mb": 10,
        "parser": "json",
    },
    # PDF
    "application/pdf": {
        "extensions": [".pdf"],
        "max_size_mb": 10,
        "parser": "pdf",
    },
    # Office
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": {
        "extensions": [".docx"],
        "max_size_mb": 10,
        "parser": "docx",
    },
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": {
        "extensions": [".xlsx"],
        "max_size_mb": 10,
        "parser": "xlsx",
    },
    # HTML
    "text/html": {
        "extensions": [".html", ".htm"],
        "max_size_mb": 5,
        "parser": "html",
    },
    # 压缩包
    "application/zip": {
        "extensions": [".zip"],
        "max_size_mb": 50,
        "parser": "zip",
    },
    "application/x-tar": {
        "extensions": [".tar"],
        "max_size_mb": 50,
        "parser": "tar",
    },
    "application/gzip": {
        "extensions": [".gz", ".tar.gz", ".tgz"],
        "max_size_mb": 50,
        "parser": "gzip",
    },
    # 图片
    "image/png": {
        "extensions": [".png"],
        "max_size_mb": 10,
        "parser": "image",
    },
    "image/jpeg": {
        "extensions": [".jpg", ".jpeg"],
        "max_size_mb": 10,
        "parser": "image",
    },
    "image/webp": {
        "extensions": [".webp"],
        "max_size_mb": 10,
        "parser": "image",
    },
}


def get_extension_to_mime() -> dict[str, str]:
    """构建扩展名到 MIME 类型的映射"""
    mapping = {}
    for mime, info in SUPPORTED_FORMATS.items():
        for ext in info["extensions"]:
            mapping[ext.lower()] = mime
    return mapping


EXTENSION_TO_MIME = get_extension_to_mime()
