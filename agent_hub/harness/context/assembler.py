"""上下文组装器"""

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from agent_hub.harness.context.tokens import estimate_tokens

logger = logging.getLogger(__name__)


class SegmentPriority(Enum):
    """段位优先级（越小越重要）"""

    SYSTEM = 0  # 系统提示词
    RULES = 1  # 全局规则
    TOOLS = 2  # 工具定义
    PROFILE = 3  # 用户画像
    SUMMARY = 4  # 压缩摘要
    MESSAGES = 5  # 最近消息
    TOOL_OUTPUT = 6  # 工具输出


@dataclass
class ContextSegment:
    """上下文段

    代表上下文窗口中的一个逻辑段落。
    """

    priority: SegmentPriority
    """优先级"""

    content: str | list[dict[str, Any]]
    """内容（字符串或消息列表）"""

    pinned: bool = False
    """是否固定（不参与压缩）"""

    stable: bool = False
    """是否稳定（可缓存）"""

    tokens: int = 0
    """Token 数量（缓存）"""

    metadata: dict[str, Any] = field(default_factory=dict)
    """附加元数据"""

    def estimate_tokens(self) -> int:
        """估算 Token 数"""
        if self.tokens > 0:
            return self.tokens

        if isinstance(self.content, str):
            self.tokens = estimate_tokens(self.content)
        elif isinstance(self.content, list):
            total = 0
            for msg in self.content:
                content = msg.get("content", "")
                if isinstance(content, str):
                    total += estimate_tokens(content) + 4  # 消息开销
            self.tokens = total

        return self.tokens


class ContextAssembler:
    """上下文组装器

    按固定顺序组装上下文段，支持 Token 预算管理。

    Segment Order:
        [0] System Prompt    (pinned, stable)
        [1] Global Rules     (pinned, stable)
        [2] Tool Definitions (unpinned, stable)
        [3] Profile/Skills   (unpinned, unstable)
        [4] Compact Summary  (unpinned, unstable)
        [5] Recent Messages  (unpinned, unstable)
        [6] Tool Outputs     (unpinned, unstable)

    Features:
        - 固定段位顺序（稳定前缀，利于缓存）
        - Token 预算检查
        - 自动截断
    """

    def __init__(self, token_budget: int = 24000):
        """
        Args:
            token_budget: Token 预算上限
        """
        self._budget = token_budget
        self._segments: dict[SegmentPriority, ContextSegment] = {}

    def set_segment(self, segment: ContextSegment) -> "ContextAssembler":
        """设置上下文段"""
        self._segments[segment.priority] = segment
        return self

    def set_system_prompt(self, prompt: str) -> "ContextAssembler":
        """设置系统提示词"""
        return self.set_segment(ContextSegment(
            priority=SegmentPriority.SYSTEM,
            content=prompt,
            pinned=True,
            stable=True,
        ))

    def set_rules(self, rules: list[str]) -> "ContextAssembler":
        """设置全局规则"""
        content = "\n".join(f"- {rule}" for rule in rules)
        return self.set_segment(ContextSegment(
            priority=SegmentPriority.RULES,
            content=f"## 规则约束\n{content}",
            pinned=True,
            stable=True,
        ))

    def set_tools(self, tool_specs: list[dict[str, Any]]) -> "ContextAssembler":
        """设置工具定义"""
        import json

        content = json.dumps(tool_specs, ensure_ascii=False, indent=2)
        return self.set_segment(ContextSegment(
            priority=SegmentPriority.TOOLS,
            content=f"## 可用工具\n```json\n{content}\n```",
            stable=True,
        ))

    def set_profile(self, profile: str) -> "ContextAssembler":
        """设置用户画像"""
        return self.set_segment(ContextSegment(
            priority=SegmentPriority.PROFILE,
            content=f"## 用户画像\n{profile}",
        ))

    def set_summary(self, summary: str) -> "ContextAssembler":
        """设置压缩摘要"""
        return self.set_segment(ContextSegment(
            priority=SegmentPriority.SUMMARY,
            content=f"## 历史摘要\n{summary}",
        ))

    def set_messages(self, messages: list[dict[str, Any]]) -> "ContextAssembler":
        """设置最近消息"""
        return self.set_segment(ContextSegment(
            priority=SegmentPriority.MESSAGES,
            content=messages,
        ))

    def set_tool_outputs(self, outputs: list[dict[str, Any]]) -> "ContextAssembler":
        """设置工具输出"""
        import json

        content = "\n".join(
            f"### {o.get('tool', 'unknown')}\n```json\n{json.dumps(o.get('output'), ensure_ascii=False)}\n```"
            for o in outputs
        )
        return self.set_segment(ContextSegment(
            priority=SegmentPriority.TOOL_OUTPUT,
            content=f"## 工具输出\n{content}",
        ))

    def assemble(self) -> list[dict[str, Any]]:
        """
        组装上下文为消息列表。

        Returns:
            OpenAI 格式的消息列表
        """
        messages = []

        # 按优先级排序
        sorted_segments = sorted(
            self._segments.values(),
            key=lambda s: s.priority.value,
        )

        # 组装系统消息
        system_parts = []
        for seg in sorted_segments:
            if seg.priority in (
                SegmentPriority.SYSTEM,
                SegmentPriority.RULES,
                SegmentPriority.TOOLS,
                SegmentPriority.PROFILE,
                SegmentPriority.SUMMARY,
            ):
                if isinstance(seg.content, str):
                    system_parts.append(seg.content)

        if system_parts:
            messages.append({
                "role": "system",
                "content": "\n\n".join(system_parts),
            })

        # 组装对话消息
        msg_segment = self._segments.get(SegmentPriority.MESSAGES)
        if msg_segment and isinstance(msg_segment.content, list):
            messages.extend(msg_segment.content)

        # 组装工具输出
        output_segment = self._segments.get(SegmentPriority.TOOL_OUTPUT)
        if output_segment and isinstance(output_segment.content, str):
            messages.append({
                "role": "user",
                "content": output_segment.content,
            })

        return messages

    def estimate_tokens(self) -> int:
        """估算总 Token 数"""
        return sum(seg.estimate_tokens() for seg in self._segments.values())

    def exceeds_budget(self, ratio: float = 1.0) -> bool:
        """检查是否超过预算"""
        return self.estimate_tokens() > self._budget * ratio

    def get_unpinned_segments(self) -> list[ContextSegment]:
        """获取可压缩的段"""
        return [
            seg for seg in self._segments.values()
            if not seg.pinned
        ]

    def truncate_messages(self, max_messages: int) -> "ContextAssembler":
        """截断消息数量"""
        msg_segment = self._segments.get(SegmentPriority.MESSAGES)
        if msg_segment and isinstance(msg_segment.content, list):
            msg_segment.content = msg_segment.content[-max_messages:]
            msg_segment.tokens = 0  # 重置缓存
        return self

    def clear(self) -> "ContextAssembler":
        """清空所有段"""
        self._segments.clear()
        return self

    def summary(self) -> dict[str, Any]:
        """获取组装摘要"""
        return {
            "budget": self._budget,
            "used": self.estimate_tokens(),
            "segments": {
                seg.priority.name: {
                    "tokens": seg.estimate_tokens(),
                    "pinned": seg.pinned,
                    "stable": seg.stable,
                }
                for seg in self._segments.values()
            },
        }
