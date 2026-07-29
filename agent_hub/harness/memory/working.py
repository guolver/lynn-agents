"""工作记忆实现"""

import uuid
from typing import Any

from agent_hub.harness.memory.base import BaseMemoryBackend
from agent_hub.harness.memory.types import MemoryItem, MemoryKind, RecallQuery


class InMemoryBackend(BaseMemoryBackend):
    """内存存储后端

    简单的内存字典存储，适用于工作记忆等易失性场景。
    """

    def __init__(self):
        self._items: dict[str, MemoryItem] = {}

    def store(self, item: MemoryItem) -> None:
        """存储记忆条目"""
        if item.item_id is None:
            item.item_id = str(uuid.uuid4())
        self._items[item.item_id] = item

    def recall(self, query: RecallQuery) -> list[MemoryItem]:
        """召回记忆条目"""
        items = list(self._items.values())

        # 应用过滤器
        if query.filters:
            items = self._apply_filters(items, query.filters)

        return items

    def clear(self) -> None:
        """清空所有记忆"""
        self._items.clear()

    def delete(self, item_id: str) -> bool:
        """删除指定记忆"""
        if item_id in self._items:
            del self._items[item_id]
            return True
        return False

    def _apply_filters(
        self, items: list[MemoryItem], filters: dict[str, Any]
    ) -> list[MemoryItem]:
        """应用过滤条件"""
        result = items

        for key, value in filters.items():
            result = [
                item for item in result
                if item.content.get(key) == value
            ]

        return result

    def __len__(self) -> int:
        return len(self._items)


class WorkingMemory(InMemoryBackend):
    """工作记忆

    当前轮次的临时信息存储。每轮结束后应调用 clear() 清空。

    Features:
        - 基于内存的快速访问
        - 支持窗口限制
        - 自动 ID 生成
    """

    def __init__(self, max_items: int = 100):
        """
        Args:
            max_items: 最大条目数（超过时移除最旧的）
        """
        super().__init__()
        self._max_items = max_items

    def store(self, item: MemoryItem) -> None:
        """存储记忆条目（带窗口限制）"""
        # 确保是 WORKING 类型
        if item.kind != MemoryKind.WORKING:
            item = MemoryItem(
                kind=MemoryKind.WORKING,
                content=item.content,
                salience=item.salience,
                tags=item.tags,
                source=item.source,
            )

        super().store(item)

        # 窗口限制：移除最旧的
        if len(self._items) > self._max_items:
            self._evict_oldest()

    def _evict_oldest(self) -> None:
        """移除最旧的条目"""
        if not self._items:
            return

        oldest_id = min(
            self._items.keys(),
            key=lambda k: self._items[k].created_at,
        )
        del self._items[oldest_id]

    def get_recent(self, n: int = 10) -> list[MemoryItem]:
        """获取最近 n 条记忆"""
        items = sorted(
            self._items.values(),
            key=lambda x: x.created_at,
            reverse=True,
        )
        return items[:n]
