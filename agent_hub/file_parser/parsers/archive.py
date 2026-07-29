"""压缩包解析器：ZIP、TAR、GZIP。

包含 Zip 炸弹防护机制。
"""

from __future__ import annotations

import gzip
import io
import tarfile
import zipfile

from ..security import TooManyFilesError, ZipBombDetectedError
from .base import BaseParser, ParsedChunk, ParseResult


class ZipParser(BaseParser):
    """ZIP 解析器，包含 zip 炸弹防护"""

    def parse(self, file_bytes: bytes, filename: str) -> ParseResult:
        compressed_size = len(file_bytes)
        max_uncompressed = compressed_size * self.config.max_archive_ratio

        extracted_files: list[tuple[str, str]] = []
        total_size = 0
        skipped_files: list[str] = []

        with zipfile.ZipFile(io.BytesIO(file_bytes)) as zf:
            file_list = zf.namelist()

            # 检查文件数量
            if len(file_list) > self.config.max_archive_files:
                raise TooManyFilesError(len(file_list), self.config.max_archive_files)

            for info in zf.infolist():
                # 跳过目录
                if info.is_dir():
                    continue

                # 跳过隐藏文件和系统文件
                if info.filename.startswith((".", "__MACOSX", "~")):
                    continue

                # 检查单文件大小
                if info.file_size > self.config.max_file_size_bytes:
                    skipped_files.append(f"{info.filename} (too large)")
                    continue

                # 检查累计大小（防 zip 炸弹）
                total_size += info.file_size
                if total_size > max_uncompressed:
                    ratio = total_size / compressed_size
                    raise ZipBombDetectedError(ratio)

                # 只处理文本类文件
                if self._is_text_file(info.filename):
                    try:
                        content = zf.read(info.filename)
                        text = self._decode_content(content)
                        extracted_files.append((info.filename, text))
                    except Exception:
                        skipped_files.append(f"{info.filename} (decode error)")
                else:
                    skipped_files.append(f"{info.filename} (binary)")

        # 生成输出
        chunks = self._create_chunks(extracted_files, filename)
        full_text = "\n\n".join(
            f"=== {name} ===\n{content}" for name, content in extracted_files
        )
        full_text = self._truncate_text(full_text)

        return ParseResult(
            text=full_text,
            chunks=chunks,
            metadata={
                "format": "zip",
                "size_bytes": len(file_bytes),
                "file_count": len(file_list),
                "extracted_count": len(extracted_files),
                "skipped_files": skipped_files[:10],  # 只显示前 10 个
                "compression_ratio": round(total_size / compressed_size, 2) if compressed_size > 0 else 0,
            },
        )

    def _is_text_file(self, filename: str) -> bool:
        """判断是否为文本文件"""
        text_extensions = {
            ".txt", ".md", ".markdown", ".json", ".xml", ".html", ".htm",
            ".css", ".js", ".ts", ".py", ".java", ".c", ".cpp", ".h",
            ".go", ".rs", ".rb", ".php", ".yml", ".yaml", ".toml", ".ini",
            ".cfg", ".conf", ".sh", ".bash", ".zsh", ".sql", ".csv",
        }
        ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        return ext in text_extensions

    def _decode_content(self, content: bytes) -> str:
        """解码文件内容"""
        for encoding in ["utf-8", "gbk", "latin-1"]:
            try:
                return content.decode(encoding)
            except UnicodeDecodeError:
                continue
        return content.decode("latin-1")

    def _create_chunks(
        self, files: list[tuple[str, str]], archive_name: str
    ) -> list[ParsedChunk]:
        """为每个文件创建 chunk"""
        chunks: list[ParsedChunk] = []
        for name, content in files:
            chunks.append(
                ParsedChunk(
                    title=name,
                    content=content,
                    metadata={"archive": archive_name},
                )
            )
            if len(chunks) >= self.config.max_chunks:
                break
        return chunks


class TarParser(BaseParser):
    """TAR 解析器"""

    def parse(self, file_bytes: bytes, filename: str) -> ParseResult:
        extracted_files: list[tuple[str, str]] = []
        skipped_files: list[str] = []
        total_size = 0

        with tarfile.open(fileobj=io.BytesIO(file_bytes), mode="r:*") as tf:
            members = tf.getmembers()

            # 检查文件数量
            if len(members) > self.config.max_archive_files:
                raise TooManyFilesError(len(members), self.config.max_archive_files)

            for member in members:
                # 跳过目录
                if not member.isfile():
                    continue

                # 跳过隐藏文件
                if member.name.startswith((".", "__MACOSX")):
                    continue

                # 检查大小
                if member.size > self.config.max_file_size_bytes:
                    skipped_files.append(f"{member.name} (too large)")
                    continue

                total_size += member.size
                if total_size > self.config.max_archive_size_bytes:
                    skipped_files.append(f"{member.name} (archive limit reached)")
                    break

                # 只处理文本文件
                if self._is_text_file(member.name):
                    try:
                        f = tf.extractfile(member)
                        if f:
                            content = f.read()
                            text = self._decode_content(content)
                            extracted_files.append((member.name, text))
                    except Exception:
                        skipped_files.append(f"{member.name} (extract error)")
                else:
                    skipped_files.append(f"{member.name} (binary)")

        chunks = self._create_chunks(extracted_files, filename)
        full_text = "\n\n".join(
            f"=== {name} ===\n{content}" for name, content in extracted_files
        )
        full_text = self._truncate_text(full_text)

        return ParseResult(
            text=full_text,
            chunks=chunks,
            metadata={
                "format": "tar",
                "size_bytes": len(file_bytes),
                "file_count": len(members),
                "extracted_count": len(extracted_files),
                "skipped_files": skipped_files[:10],
            },
        )

    def _is_text_file(self, filename: str) -> bool:
        text_extensions = {
            ".txt", ".md", ".json", ".xml", ".html", ".css", ".js",
            ".py", ".java", ".c", ".cpp", ".go", ".rs", ".yml", ".yaml",
        }
        ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        return ext in text_extensions

    def _decode_content(self, content: bytes) -> str:
        for encoding in ["utf-8", "gbk", "latin-1"]:
            try:
                return content.decode(encoding)
            except UnicodeDecodeError:
                continue
        return content.decode("latin-1")

    def _create_chunks(
        self, files: list[tuple[str, str]], archive_name: str
    ) -> list[ParsedChunk]:
        chunks: list[ParsedChunk] = []
        for name, content in files:
            chunks.append(
                ParsedChunk(
                    title=name,
                    content=content,
                    metadata={"archive": archive_name},
                )
            )
            if len(chunks) >= self.config.max_chunks:
                break
        return chunks


class GzipParser(BaseParser):
    """GZIP 解析器"""

    def parse(self, file_bytes: bytes, filename: str) -> ParseResult:
        compressed_size = len(file_bytes)

        # 解压
        try:
            decompressed = gzip.decompress(file_bytes)
        except Exception as e:
            raise ValueError(f"Failed to decompress gzip: {e}")

        # 检查压缩比
        ratio = len(decompressed) / compressed_size if compressed_size > 0 else 0
        if ratio > self.config.max_archive_ratio:
            raise ZipBombDetectedError(ratio)

        # 检查大小
        if len(decompressed) > self.config.max_archive_size_bytes:
            raise ValueError("Decompressed content exceeds size limit")

        # 尝试解码为文本
        text = self._decode_content(decompressed)
        text = self._truncate_text(text)
        chunks = self._split_by_length(text, filename)

        return ParseResult(
            text=text,
            chunks=chunks,
            metadata={
                "format": "gzip",
                "compressed_size": compressed_size,
                "decompressed_size": len(decompressed),
                "compression_ratio": round(ratio, 2),
            },
        )

    def _decode_content(self, content: bytes) -> str:
        for encoding in ["utf-8", "gbk", "latin-1"]:
            try:
                return content.decode(encoding)
            except UnicodeDecodeError:
                continue
        return content.decode("latin-1")
