"""子 Agent 类型定义"""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class SubTask:
    """子任务输入

    通过显式传递输入参数，避免共享内存。
    """

    goal: str
    """任务目标描述"""

    inputs: dict[str, Any] = field(default_factory=dict)
    """显式输入参数"""

    max_tool_calls: int = 5
    """本次任务工具调用上限"""

    max_tokens: int = 2000
    """本次任务 Token 上限"""

    timeout_seconds: float = 60.0
    """超时时间（秒）"""

    metadata: dict[str, Any] = field(default_factory=dict)
    """附加元数据"""


@dataclass
class SubResult:
    """子任务输出

    只返回摘要和结构化数据，不回传完整历史。
    """

    summary: str
    """回传主上下文的摘要"""

    structured: dict[str, Any] = field(default_factory=dict)
    """结构化输出（JSON 可解析）"""

    tokens_used: int = 0
    """消耗的 Token 数"""

    tool_calls_made: int = 0
    """执行的工具调用数"""

    success: bool = True
    """是否成功完成"""

    error: str | None = None
    """错误信息（如有）"""

    metadata: dict[str, Any] = field(default_factory=dict)
    """附加元数据"""

    @classmethod
    def failure(cls, error: str, summary: str | None = None) -> "SubResult":
        """创建失败结果"""
        return cls(
            summary=summary or f"Task failed: {error}",
            success=False,
            error=error,
        )
