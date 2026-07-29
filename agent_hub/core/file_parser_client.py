"""文件解析沙箱客户端。

主服务通过此客户端调用独立部署的文件解析沙箱服务。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any

import httpx


class FileParserError(Exception):
    """文件解析错误"""

    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


@dataclass
class ParsedChunk:
    """解析后的文本块"""

    title: str
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ParseResult:
    """文件解析结果"""

    text: str
    chunks: list[ParsedChunk]
    metadata: dict[str, Any]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ParseResult":
        return cls(
            text=data["text"],
            chunks=[
                ParsedChunk(
                    title=c["title"],
                    content=c["content"],
                    metadata=c.get("metadata", {}),
                )
                for c in data.get("chunks", [])
            ],
            metadata=data.get("metadata", {}),
        )


class FileParserClient:
    """
    文件解析沙箱客户端。

    使用示例:
        client = FileParserClient()
        result = await client.parse(pdf_bytes, "resume.pdf")
        print(result.text)
    """

    def __init__(
        self,
        base_url: str | None = None,
        timeout: float = 35.0,
    ):
        """
        初始化客户端。

        Args:
            base_url: 沙箱服务地址，默认从环境变量 FILE_PARSER_URL 读取
            timeout: 请求超时时间（秒），应比沙箱内部超时略长
        """
        self.base_url = base_url or os.getenv(
            "FILE_PARSER_URL", "http://file-parser:8001"
        )
        self.timeout = timeout
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        """获取或创建 HTTP 客户端"""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self.timeout,
            )
        return self._client

    async def parse(
        self,
        file_bytes: bytes,
        filename: str,
        options: dict[str, Any] | None = None,
    ) -> ParseResult:
        """
        解析文件。

        Args:
            file_bytes: 文件二进制内容
            filename: 原始文件名（用于格式检测）
            options: 可选的解析选项

        Returns:
            ParseResult: 解析结果

        Raises:
            FileParserError: 解析失败
        """
        client = await self._get_client()

        response = await client.post(
            "/parse",
            files={"file": (filename, file_bytes)},
            data={"options": json.dumps(options or {})},
        )

        result = response.json()

        if not result.get("success"):
            error = result.get("error", {})
            raise FileParserError(
                code=error.get("code", "UNKNOWN_ERROR"),
                message=error.get("message", "Unknown error"),
            )

        return ParseResult.from_dict(result["data"])

    async def health(self) -> bool:
        """
        检查沙箱服务健康状态。

        Returns:
            bool: 服务是否健康
        """
        try:
            client = await self._get_client()
            response = await client.get("/health")
            return response.status_code == 200
        except Exception:
            return False

    async def get_formats(self) -> list[dict[str, Any]]:
        """
        获取支持的文件格式列表。

        Returns:
            list: 格式信息列表
        """
        client = await self._get_client()
        response = await client.get("/formats")
        response.raise_for_status()
        return response.json().get("formats", [])

    async def close(self):
        """关闭客户端连接"""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self) -> "FileParserClient":
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()


# 便捷函数
async def parse_file(
    file_bytes: bytes,
    filename: str,
    options: dict[str, Any] | None = None,
) -> ParseResult:
    """
    解析文件的便捷函数。

    每次调用会创建新的客户端连接，适合偶发调用。
    高频调用请使用 FileParserClient 实例。
    """
    async with FileParserClient() as client:
        return await client.parse(file_bytes, filename, options)
