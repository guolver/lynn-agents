"""情景记忆实现"""

import json
import logging
import uuid
from pathlib import Path
from typing import Any

from agent_hub.harness.memory.base import BaseMemoryBackend
from agent_hub.harness.memory.types import MemoryItem, MemoryKind, RecallQuery

logger = logging.getLogger(__name__)


class EpisodicMemory(BaseMemoryBackend):
    """情景记忆

    历史事件和交互记录，会话级持久化。

    Features:
        - 内存 + 可选持久化
        - 时间戳索引
        - 会话隔离
    """

    def __init__(self, session_id: str | None = None, persist_backend: "BaseMemoryBackend | None" = None):
        """
        Args:
            session_id: 会话 ID（用于隔离）
            persist_backend: 可选的持久化后端
        """
        self._session_id = session_id
        self._persist = persist_backend
        self._items: dict[str, MemoryItem] = {}

        # 如果有持久化后端，加载已有数据
        if self._persist:
            self._load_from_persist()

    def _load_from_persist(self) -> None:
        """从持久化后端加载"""
        items = self._persist.recall(RecallQuery(kinds=[MemoryKind.EPISODIC], limit=10000))
        for item in items:
            if item.item_id:
                self._items[item.item_id] = item

    def store(self, item: MemoryItem) -> None:
        """存储记忆条目"""
        if item.item_id is None:
            item.item_id = str(uuid.uuid4())

        # 确保类型正确
        if item.kind != MemoryKind.EPISODIC:
            item = MemoryItem(
                kind=MemoryKind.EPISODIC,
                content=item.content,
                salience=item.salience,
                tags=item.tags,
                source=item.source,
                item_id=item.item_id,
            )

        self._items[item.item_id] = item

        # 同步到持久化后端
        if self._persist:
            self._persist.store(item)

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
        if self._persist:
            self._persist.clear()

    def delete(self, item_id: str) -> bool:
        """删除指定记忆"""
        if item_id in self._items:
            del self._items[item_id]
            if self._persist:
                self._persist.delete(item_id)
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


class JsonlEpisodicBackend(BaseMemoryBackend):
    """JSONL 文件持久化后端

    每行一个 JSON 对象，追加写入。
    """

    def __init__(self, path: Path | str):
        """
        Args:
            path: JSONL 文件路径
        """
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def store(self, item: MemoryItem) -> None:
        """追加写入"""
        with open(self._path, "a", encoding="utf-8") as f:
            f.write(json.dumps(item.to_dict(), ensure_ascii=False) + "\n")

    def recall(self, query: RecallQuery) -> list[MemoryItem]:
        """读取所有条目"""
        if not self._path.exists():
            return []

        items = []
        with open(self._path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        data = json.loads(line)
                        items.append(MemoryItem.from_dict(data))
                    except json.JSONDecodeError:
                        logger.warning("Invalid JSON line in %s", self._path)

        return items

    def clear(self) -> None:
        """清空文件"""
        if self._path.exists():
            self._path.unlink()

    def delete(self, item_id: str) -> bool:
        """删除条目（需要重写整个文件）"""
        if not self._path.exists():
            return False

        items = self.recall(RecallQuery(kinds=[MemoryKind.EPISODIC], limit=10000))
        new_items = [item for item in items if item.item_id != item_id]

        if len(new_items) == len(items):
            return False

        # 重写文件
        self.clear()
        for item in new_items:
            self.store(item)

        return True
