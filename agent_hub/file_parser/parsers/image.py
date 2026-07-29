"""图片解析器。

支持 OCR 文字提取（需要 pytesseract）或基础图片信息提取。
"""

from __future__ import annotations

import io

from .base import BaseParser, ParsedChunk, ParseResult


class ImageParser(BaseParser):
    """图片解析器"""

    def parse(self, file_bytes: bytes, filename: str) -> ParseResult:
        from PIL import Image

        img = Image.open(io.BytesIO(file_bytes))

        # 检查图片尺寸
        width, height = img.size
        pixels = width * height
        if pixels > self.config.max_image_pixels:
            raise ValueError(
                f"Image too large: {pixels} pixels exceeds limit of {self.config.max_image_pixels}"
            )

        # 基础信息
        metadata = {
            "format": img.format or "unknown",
            "mode": img.mode,
            "width": width,
            "height": height,
            "size_bytes": len(file_bytes),
        }

        # 尝试 OCR
        text = ""
        ocr_available = False

        try:
            import pytesseract

            ocr_available = True

            # 转换为 RGB（OCR 需要）
            if img.mode != "RGB":
                img = img.convert("RGB")

            # 执行 OCR
            text = pytesseract.image_to_string(img, lang="chi_sim+eng")
            text = text.strip()
            metadata["ocr"] = True
            metadata["ocr_char_count"] = len(text)

        except ImportError:
            # pytesseract 未安装
            metadata["ocr"] = False
            metadata["ocr_error"] = "pytesseract not installed"

        except Exception as e:
            metadata["ocr"] = False
            metadata["ocr_error"] = str(e)

        # 生成 chunks
        chunks: list[ParsedChunk] = []
        if text:
            text = self._truncate_text(text)
            chunks = self._split_by_length(text, filename)

        return ParseResult(
            text=text,
            chunks=chunks,
            metadata=metadata,
        )
