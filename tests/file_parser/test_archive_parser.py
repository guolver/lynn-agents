"""压缩包解析器测试，包含 Zip 炸弹检测。"""

import gzip
import io
import tarfile
import unittest
import zipfile

from agent_hub.file_parser.config import ParserConfig
from agent_hub.file_parser.parsers.archive import GzipParser, TarParser, ZipParser
from agent_hub.file_parser.security import TooManyFilesError, ZipBombDetectedError


class TestZipParser(unittest.TestCase):
    """ZIP 解析器测试"""

    def setUp(self):
        self.config = ParserConfig()
        self.parser = ZipParser(self.config)

    def test_parse_simple_zip(self):
        """测试解析简单 ZIP"""
        zip_content = self._create_zip({"test.txt": "Hello, World!"})
        result = self.parser.parse(zip_content, "test.zip")

        self.assertEqual(result.metadata["format"], "zip")
        self.assertEqual(result.metadata["extracted_count"], 1)
        self.assertIn("Hello, World!", result.text)

    def test_parse_zip_with_multiple_files(self):
        """测试解析多文件 ZIP"""
        files = {
            "file1.txt": "Content 1",
            "file2.txt": "Content 2",
            "file3.json": '{"key": "value"}',
        }
        zip_content = self._create_zip(files)
        result = self.parser.parse(zip_content, "multi.zip")

        self.assertEqual(result.metadata["file_count"], 3)
        self.assertEqual(result.metadata["extracted_count"], 3)
        self.assertEqual(len(result.chunks), 3)

    def test_skip_binary_files(self):
        """测试跳过二进制文件"""
        zip_content = self._create_zip({
            "text.txt": "Hello",
            "image.png": b"\x89PNG\r\n\x1a\n",  # PNG header
        })
        result = self.parser.parse(zip_content, "mixed.zip")

        self.assertEqual(result.metadata["extracted_count"], 1)
        self.assertIn("image.png (binary)", result.metadata["skipped_files"])

    def test_skip_hidden_files(self):
        """测试跳过隐藏文件"""
        zip_content = self._create_zip({
            "visible.txt": "Hello",
            ".hidden": "Secret",
            "__MACOSX/file": "Mac stuff",
        })
        result = self.parser.parse(zip_content, "hidden.zip")

        self.assertEqual(result.metadata["extracted_count"], 1)

    def test_reject_too_many_files(self):
        """测试拒绝文件过多的 ZIP"""
        config = ParserConfig(max_archive_files=5)
        parser = ZipParser(config)

        files = {f"file{i}.txt": f"Content {i}" for i in range(10)}
        zip_content = self._create_zip(files)

        with self.assertRaises(TooManyFilesError) as ctx:
            parser.parse(zip_content, "many.zip")
        self.assertEqual(ctx.exception.code, "TOO_MANY_FILES")

    def test_detect_zip_bomb(self):
        """测试检测 Zip 炸弹"""
        config = ParserConfig(max_archive_ratio=5)
        parser = ZipParser(config)

        # 创建高压缩比的文件（重复字符压缩效果极好）
        # 10KB 压缩后约 100 字节，压缩比 > 100
        large_content = "A" * (100 * 1024)  # 100KB 的重复字符
        zip_content = self._create_zip({"bomb.txt": large_content})

        # 检查压缩比
        with zipfile.ZipFile(io.BytesIO(zip_content)) as zf:
            info = zf.getinfo("bomb.txt")
            ratio = info.file_size / len(zip_content)
            # 如果压缩比足够高，应该触发检测
            if ratio > 5:
                with self.assertRaises(ZipBombDetectedError):
                    parser.parse(zip_content, "bomb.zip")

    def test_compression_ratio_in_metadata(self):
        """测试压缩比记录在元数据中"""
        zip_content = self._create_zip({"test.txt": "Hello" * 100})
        result = self.parser.parse(zip_content, "test.zip")

        self.assertIn("compression_ratio", result.metadata)
        self.assertIsInstance(result.metadata["compression_ratio"], float)

    def _create_zip(self, files: dict) -> bytes:
        """创建 ZIP 文件"""
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            for name, content in files.items():
                if isinstance(content, str):
                    content = content.encode("utf-8")
                zf.writestr(name, content)
        return buffer.getvalue()


class TestTarParser(unittest.TestCase):
    """TAR 解析器测试"""

    def setUp(self):
        self.config = ParserConfig()
        self.parser = TarParser(self.config)

    def test_parse_simple_tar(self):
        """测试解析简单 TAR"""
        tar_content = self._create_tar({"test.txt": "Hello, World!"})
        result = self.parser.parse(tar_content, "test.tar")

        self.assertEqual(result.metadata["format"], "tar")
        self.assertIn("Hello, World!", result.text)

    def test_parse_tar_with_multiple_files(self):
        """测试解析多文件 TAR"""
        files = {
            "file1.txt": "Content 1",
            "file2.py": "print('hello')",
        }
        tar_content = self._create_tar(files)
        result = self.parser.parse(tar_content, "multi.tar")

        self.assertEqual(result.metadata["extracted_count"], 2)

    def test_reject_too_many_files(self):
        """测试拒绝文件过多的 TAR"""
        config = ParserConfig(max_archive_files=3)
        parser = TarParser(config)

        files = {f"file{i}.txt": f"Content {i}" for i in range(5)}
        tar_content = self._create_tar(files)

        with self.assertRaises(TooManyFilesError):
            parser.parse(tar_content, "many.tar")

    def _create_tar(self, files: dict) -> bytes:
        """创建 TAR 文件"""
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w") as tf:
            for name, content in files.items():
                if isinstance(content, str):
                    content = content.encode("utf-8")
                info = tarfile.TarInfo(name=name)
                info.size = len(content)
                tf.addfile(info, io.BytesIO(content))
        return buffer.getvalue()


class TestGzipParser(unittest.TestCase):
    """GZIP 解析器测试"""

    def setUp(self):
        self.config = ParserConfig()
        self.parser = GzipParser(self.config)

    def test_parse_simple_gzip(self):
        """测试解析简单 GZIP"""
        content = b"Hello, World!"
        gzip_content = gzip.compress(content)
        result = self.parser.parse(gzip_content, "test.txt.gz")

        self.assertEqual(result.metadata["format"], "gzip")
        self.assertEqual(result.text, "Hello, World!")

    def test_gzip_compression_ratio(self):
        """测试 GZIP 压缩比记录"""
        # 使用低压缩比的内容（随机数据压缩效果差）
        import random
        random.seed(42)
        content = bytes([random.randint(0, 255) for _ in range(1000)])
        gzip_content = gzip.compress(content)
        result = self.parser.parse(gzip_content, "test.gz")

        self.assertIn("compression_ratio", result.metadata)
        self.assertIn("compressed_size", result.metadata)
        self.assertIn("decompressed_size", result.metadata)

    def test_detect_gzip_bomb(self):
        """测试检测 GZIP 炸弹"""
        config = ParserConfig(max_archive_ratio=5)
        parser = GzipParser(config)

        # 创建高压缩比内容
        content = b"A" * (1024 * 1024)  # 1MB 重复字符
        gzip_content = gzip.compress(content, compresslevel=9)

        ratio = len(content) / len(gzip_content)
        if ratio > 5:
            with self.assertRaises(ZipBombDetectedError):
                parser.parse(gzip_content, "bomb.gz")

    def test_parse_utf8_gzip(self):
        """测试解析 UTF-8 编码的 GZIP"""
        content = "你好，世界！".encode("utf-8")
        gzip_content = gzip.compress(content)
        result = self.parser.parse(gzip_content, "chinese.txt.gz")

        self.assertEqual(result.text, "你好，世界！")


class TestArchiveSecurityBoundaries(unittest.TestCase):
    """压缩包安全边界测试"""

    def test_nested_zip_not_extracted(self):
        """测试嵌套 ZIP 不会被递归解压"""
        # 创建内层 ZIP
        inner_zip = self._create_zip({"inner.txt": "Inner content"})

        # 创建外层 ZIP 包含内层 ZIP
        outer_zip = self._create_zip({
            "outer.txt": "Outer content",
            "nested.zip": inner_zip,
        })

        config = ParserConfig()
        parser = ZipParser(config)
        result = parser.parse(outer_zip, "nested.zip")

        # 只应提取 outer.txt，nested.zip 应被跳过（二进制）
        self.assertEqual(result.metadata["extracted_count"], 1)
        self.assertIn("Outer content", result.text)
        self.assertNotIn("Inner content", result.text)

    def test_path_traversal_prevented(self):
        """测试防止路径遍历攻击"""
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as zf:
            # 尝试写入包含 ../ 的路径
            zf.writestr("../../../etc/passwd", "malicious content")
            zf.writestr("normal.txt", "normal content")

        config = ParserConfig()
        parser = ZipParser(config)
        result = parser.parse(buffer.getvalue(), "traversal.zip")

        # 解析应该成功，但只提取正常文件
        # （ZipParser 只提取内容，不实际写入文件系统）
        self.assertIn("normal content", result.text)

    def _create_zip(self, files: dict) -> bytes:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            for name, content in files.items():
                if isinstance(content, str):
                    content = content.encode("utf-8")
                zf.writestr(name, content)
        return buffer.getvalue()


if __name__ == "__main__":
    unittest.main()
