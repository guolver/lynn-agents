"""文件安全检查。

在解析前验证文件类型、大小和基本安全性。
"""

from __future__ import annotations

import io
import struct
from dataclasses import dataclass
from pathlib import Path

from .config import EXTENSION_TO_MIME, SUPPORTED_FORMATS, ParserConfig


class FileValidationError(Exception):
    """文件验证错误基类"""

    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


class FileTooLargeError(FileValidationError):
    def __init__(self, size: int, limit: int):
        super().__init__(
            "FILE_TOO_LARGE",
            f"File size {size} bytes exceeds limit of {limit} bytes",
        )


class UnsupportedFormatError(FileValidationError):
    def __init__(self, format_info: str):
        super().__init__(
            "UNSUPPORTED_FORMAT",
            f"Unsupported file format: {format_info}",
        )


class MimeTypeMismatchError(FileValidationError):
    def __init__(self, expected: str, actual: str):
        super().__init__(
            "MIME_TYPE_MISMATCH",
            f"File extension suggests {expected}, but content is {actual}",
        )


class ZipBombDetectedError(FileValidationError):
    def __init__(self, ratio: float):
        super().__init__(
            "ZIP_BOMB_DETECTED",
            f"Compression ratio {ratio:.1f}x exceeds safety limit",
        )


class TooManyFilesError(FileValidationError):
    def __init__(self, count: int, limit: int):
        super().__init__(
            "TOO_MANY_FILES",
            f"Archive contains {count} files, exceeds limit of {limit}",
        )


class ParseTimeoutError(FileValidationError):
    def __init__(self, timeout: int):
        super().__init__(
            "PARSE_TIMEOUT",
            f"Parsing exceeded timeout of {timeout} seconds",
        )


@dataclass
class FileInfo:
    """验证后的文件信息"""

    mime_type: str
    extension: str
    size_bytes: int
    parser_name: str


# 文件魔数签名
MAGIC_SIGNATURES: dict[bytes, str] = {
    # PDF
    b"%PDF": "application/pdf",
    # ZIP (also docx, xlsx)
    b"PK\x03\x04": "application/zip",
    b"PK\x05\x06": "application/zip",  # empty archive
    # GZIP
    b"\x1f\x8b": "application/gzip",
    # PNG
    b"\x89PNG\r\n\x1a\n": "image/png",
    # JPEG
    b"\xff\xd8\xff": "image/jpeg",
    # WEBP
    b"RIFF": "image/webp",  # needs additional check for WEBP
}


def detect_mime_by_magic(file_bytes: bytes) -> str | None:
    """通过文件魔数检测 MIME 类型"""
    if len(file_bytes) < 8:
        return None

    # 检查各种魔数
    for signature, mime in MAGIC_SIGNATURES.items():
        if file_bytes.startswith(signature):
            # WEBP 需要额外检查
            if signature == b"RIFF" and len(file_bytes) >= 12:
                if file_bytes[8:12] != b"WEBP":
                    continue
            return mime

    # Office 文件 (ZIP 格式) 需要检查内部结构
    if file_bytes.startswith(b"PK\x03\x04"):
        return _detect_office_type(file_bytes)

    return None


def _detect_office_type(file_bytes: bytes) -> str:
    """检测 Office 文件的具体类型"""
    import zipfile

    try:
        with zipfile.ZipFile(io.BytesIO(file_bytes)) as zf:
            names = zf.namelist()
            if "[Content_Types].xml" in names:
                # 读取 content types 判断具体类型
                if any("word/" in n for n in names):
                    return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                if any("xl/" in n for n in names):
                    return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            return "application/zip"
    except Exception:
        return "application/zip"


def get_mime_from_extension(filename: str) -> str | None:
    """根据文件扩展名获取 MIME 类型"""
    ext = Path(filename).suffix.lower()
    return EXTENSION_TO_MIME.get(ext)


def validate_file(
    file_bytes: bytes,
    filename: str,
    config: ParserConfig,
) -> FileInfo:
    """
    验证文件安全性。

    检查项：
    1. 文件大小
    2. 扩展名是否支持
    3. 魔数验证（真实文件类型）
    4. 扩展名与内容是否匹配

    Returns:
        FileInfo: 验证通过的文件信息

    Raises:
        FileValidationError: 验证失败
    """
    size = len(file_bytes)
    ext = Path(filename).suffix.lower()

    # 1. 检查扩展名是否支持
    mime_from_ext = get_mime_from_extension(filename)
    if mime_from_ext is None:
        raise UnsupportedFormatError(f"extension '{ext}'")

    # 2. 获取格式配置
    format_config = SUPPORTED_FORMATS.get(mime_from_ext)
    if format_config is None:
        raise UnsupportedFormatError(mime_from_ext)

    # 3. 检查文件大小
    max_size = format_config["max_size_mb"] * 1024 * 1024
    if size > max_size:
        raise FileTooLargeError(size, max_size)

    # 4. 魔数验证（对于二进制格式）
    detected_mime = detect_mime_by_magic(file_bytes)

    # 文本格式无法通过魔数检测，跳过验证
    text_mimes = {"text/plain", "text/markdown", "application/json", "text/html"}
    if mime_from_ext not in text_mimes:
        if detected_mime is None:
            raise UnsupportedFormatError("Unable to detect file type from content")

        # Office 文件都是 ZIP 格式，需要特殊处理
        office_mimes = {
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        }
        if mime_from_ext in office_mimes:
            if detected_mime not in office_mimes and detected_mime != "application/zip":
                raise MimeTypeMismatchError(mime_from_ext, detected_mime)
        elif detected_mime != mime_from_ext:
            # 允许 ZIP 类型的文件
            if not (mime_from_ext == "application/zip" and detected_mime in office_mimes):
                raise MimeTypeMismatchError(mime_from_ext, detected_mime)

    return FileInfo(
        mime_type=mime_from_ext,
        extension=ext,
        size_bytes=size,
        parser_name=format_config["parser"],
    )
