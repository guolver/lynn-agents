"""记忆系统类型定义"""

import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any


class MemoryKind(Enum):
    """记忆层级"""

    WORKING = auto()
    """工作记忆：当前轮次的临时信息，轮次结束后清空"""

    EPISODIC = auto()
    """情景记忆：历史事件和交互记录，会话级持久化"""

    SEMANTIC = auto()
    """语义记忆：事实性知识和画像，跨会话持久化"""

    PROCEDURAL = auto()
    """程序记忆：规则和约束，静态配置"""


@dataclass
class MemoryItem:
    """记忆条目"""

    kind: MemoryKind
    """记忆层级"""

    content: dict[str, Any]
    """记忆内容"""

    salience: float = 1.0
    """显著性分数（0.0 - 1.0）"""

    created_at: float = field(default_factory=time.time)
    """创建时间戳"""

    tags: list[str] = field(default_factory=list)
    """标签（用于过滤）"""

    source: str | None = None
    """来源标识"""

    item_id: str | None = None
    """唯一标识"""

    def effective_salience(self, decay_rate: float = 0.1) -> float:
        """
        计算时间衰减后的有效显著性。

        公式: salience / (1 + decay_rate * age_seconds)

        Args:
            decay_rate: 衰减率

        Returns:
            有效显著性
        """
        age = time.time() - self.created_at
        return self.salience / (1.0 + decay_rate * age)

    def matches_tags(self, required_tags: list[str]) -> bool:
        """检查是否匹配所有必需标签"""
        return all(tag in self.tags for tag in required_tags)

    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        return {
            "kind": self.kind.name,
            "content": self.content,
            "salience": self.salience,
            "created_at": self.created_at,
            "tags": self.tags,
            "source": self.source,
            "item_id": self.item_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MemoryItem":
        """从字典创建"""
        return cls(
            kind=MemoryKind[data["kind"]],
            content=data["content"],
            salience=data.get("salience", 1.0),
            created_at=data.get("created_at", time.time()),
            tags=data.get("tags", []),
            source=data.get("source"),
            item_id=data.get("item_id"),
        )


@dataclass
class RecallQuery:
    """记忆召回查询"""

    kinds: list[MemoryKind]
    """查询的记忆层级"""

    filters: dict[str, Any] = field(default_factory=dict)
    """过滤条件"""

    tags: list[str] = field(default_factory=list)
    """必需标签"""

    limit: int = 10
    """返回数量上限"""

    min_salience: float = 0.0
    """最小显著性阈值"""

    decay_rate: float = 0.1
    """时间衰减率"""

    order_by_salience: bool = True
    """是否按显著性排序"""

    include_content: bool = True
    """是否包含内容"""


@dataclass
class PromoteRequest:
    """记忆提升请求"""

    item: MemoryItem
    """待提升的记忆条目"""

    to_kind: MemoryKind
    """目标层级"""

    salience_multiplier: float = 1.0
    """显著性乘数"""
