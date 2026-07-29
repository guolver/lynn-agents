"""记忆系统基础设施"""

import logging
from abc import ABC, abstractmethod
from typing import Protocol, runtime_checkable

from agent_hub.harness.memory.types import MemoryItem, MemoryKind, RecallQuery

logger = logging.getLogger(__name__)


@runtime_checkable
class MemoryBackend(Protocol):
    """记忆后端协议"""

    def store(self, item: MemoryItem) -> None:
        """存储记忆条目"""
        ...

    def recall(self, query: RecallQuery) -> list[MemoryItem]:
        """召回记忆条目"""
        ...

    def clear(self) -> None:
        """清空所有记忆"""
        ...

    def delete(self, item_id: str) -> bool:
        """删除指定记忆"""
        ...


class BaseMemoryBackend(ABC):
    """记忆后端基类"""

    @abstractmethod
    def store(self, item: MemoryItem) -> None:
        """存储记忆条目"""
        ...

    @abstractmethod
    def recall(self, query: RecallQuery) -> list[MemoryItem]:
        """召回记忆条目"""
        ...

    @abstractmethod
    def clear(self) -> None:
        """清空所有记忆"""
        ...

    def delete(self, item_id: str) -> bool:
        """删除指定记忆（默认不支持）"""
        return False


class MemoryService:
    """四层记忆编排器

    管理四个层级的记忆：
    - WORKING: 工作记忆（当前轮次）
    - EPISODIC: 情景记忆（历史事件）
    - SEMANTIC: 语义记忆（事实知识）
    - PROCEDURAL: 程序记忆（规则约束）

    Features:
        - 统一的存储和召回接口
        - 按显著性排序的召回结果
        - 记忆层级提升（Working → Episodic → Semantic）
        - 多层联合查询
    """

    def __init__(
        self,
        working: MemoryBackend,
        episodic: MemoryBackend,
        semantic: MemoryBackend,
        procedural: MemoryBackend,
    ):
        """
        Args:
            working: 工作记忆后端
            episodic: 情景记忆后端
            semantic: 语义记忆后端
            procedural: 程序记忆后端
        """
        self._backends: dict[MemoryKind, MemoryBackend] = {
            MemoryKind.WORKING: working,
            MemoryKind.EPISODIC: episodic,
            MemoryKind.SEMANTIC: semantic,
            MemoryKind.PROCEDURAL: procedural,
        }

    def remember(self, item: MemoryItem) -> None:
        """
        存储记忆条目。

        Args:
            item: 记忆条目
        """
        backend = self._backends[item.kind]
        backend.store(item)
        logger.debug(
            "Stored memory: kind=%s, salience=%.2f",
            item.kind.name,
            item.salience,
        )

    def recall(self, query: RecallQuery) -> list[MemoryItem]:
        """
        召回记忆条目。

        从指定的记忆层级中召回，按有效显著性排序。

        Args:
            query: 召回查询

        Returns:
            记忆条目列表
        """
        items: list[MemoryItem] = []

        for kind in query.kinds:
            backend = self._backends.get(kind)
            if backend:
                kind_items = backend.recall(query)
                items.extend(kind_items)

        # 过滤最小显著性
        if query.min_salience > 0:
            items = [
                item for item in items
                if item.effective_salience(query.decay_rate) >= query.min_salience
            ]

        # 过滤标签
        if query.tags:
            items = [item for item in items if item.matches_tags(query.tags)]

        # 按显著性排序
        if query.order_by_salience:
            items.sort(
                key=lambda x: x.effective_salience(query.decay_rate),
                reverse=True,
            )

        # 限制数量
        items = items[:query.limit]

        logger.debug(
            "Recalled %d memories from %s",
            len(items),
            [k.name for k in query.kinds],
        )

        return items

    def promote(self, item: MemoryItem, to_kind: MemoryKind) -> MemoryItem:
        """
        提升记忆层级。

        将记忆从低层级复制到高层级（如 WORKING → EPISODIC）。

        Args:
            item: 待提升的记忆
            to_kind: 目标层级

        Returns:
            新创建的记忆条目
        """
        new_item = MemoryItem(
            kind=to_kind,
            content=item.content.copy(),
            salience=item.salience,
            tags=item.tags.copy(),
            source=item.source,
        )

        self._backends[to_kind].store(new_item)

        logger.info(
            "Promoted memory: %s -> %s",
            item.kind.name,
            to_kind.name,
        )

        return new_item

    def clear_working(self) -> None:
        """清空工作记忆"""
        self._backends[MemoryKind.WORKING].clear()
        logger.debug("Cleared working memory")

    def clear_all(self) -> None:
        """清空所有记忆"""
        for backend in self._backends.values():
            backend.clear()
        logger.info("Cleared all memory")

    def get_backend(self, kind: MemoryKind) -> MemoryBackend:
        """获取指定层级的后端"""
        return self._backends[kind]

    def summarize(self) -> dict[str, int]:
        """获取各层记忆数量摘要"""
        return {
            kind.name: len(backend.recall(RecallQuery(kinds=[kind], limit=10000)))
            for kind, backend in self._backends.items()
        }
