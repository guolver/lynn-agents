"""文件解析器集合。"""

from .base import BaseParser, ParsedChunk, ParseResult
from .text import TextParser, MarkdownParser, JsonParser
from .pdf import PdfParser
from .office import DocxParser, XlsxParser
from .html import HtmlParser
from .archive import ZipParser, TarParser, GzipParser
from .image import ImageParser

__all__ = [
    "BaseParser",
    "ParsedChunk",
    "ParseResult",
    "TextParser",
    "MarkdownParser",
    "JsonParser",
    "PdfParser",
    "DocxParser",
    "XlsxParser",
    "HtmlParser",
    "ZipParser",
    "TarParser",
    "GzipParser",
    "ImageParser",
]


# 解析器注册表
PARSER_REGISTRY: dict[str, type[BaseParser]] = {
    "text": TextParser,
    "markdown": MarkdownParser,
    "json": JsonParser,
    "pdf": PdfParser,
    "docx": DocxParser,
    "xlsx": XlsxParser,
    "html": HtmlParser,
    "zip": ZipParser,
    "tar": TarParser,
    "gzip": GzipParser,
    "image": ImageParser,
}


def get_parser(parser_name: str) -> type[BaseParser]:
    """根据名称获取解析器类"""
    parser_cls = PARSER_REGISTRY.get(parser_name)
    if parser_cls is None:
        raise ValueError(f"Unknown parser: {parser_name}")
    return parser_cls
