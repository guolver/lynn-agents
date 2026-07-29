"""语义记忆实现"""

import logging
import uuid
from typing import Any

from agent_hub.harness.memory.base import BaseMemoryBackend
from agent_hub.harness.memory.types import MemoryItem, MemoryKind, RecallQuery

logger = logging.getLogger(__name__)


class SemanticMemory(BaseMemoryBackend):
    """语义记忆

    事实性知识和画像，跨会话持久化。

    Features:
        - 基于键值的事实存储
        - 支持向量检索（可选）
        - 跨会话持久化
    """

    def __init__(self, persist_backend: "BaseMemoryBackend | None" = None):
        """
        Args:
            persist_backend: 可选的持久化后端
        """
        self._persist = persist_backend
        self._items: dict[str, MemoryItem] = {}

        if self._persist:
            self._load_from_persist()

    def _load_from_persist(self) -> None:
        """从持久化后端加载"""
        items = self._persist.recall(RecallQuery(kinds=[MemoryKind.SEMANTIC], limit=10000))
        for item in items:
            if item.item_id:
                self._items[item.item_id] = item

    def store(self, item: MemoryItem) -> None:
        """存储记忆条目"""
        if item.item_id is None:
            item.item_id = str(uuid.uuid4())

        if item.kind != MemoryKind.SEMANTIC:
            item = MemoryItem(
                kind=MemoryKind.SEMANTIC,
                content=item.content,
                salience=item.salience,
                tags=item.tags,
                source=item.source,
                item_id=item.item_id,
            )

        self._items[item.item_id] = item

        if self._persist:
            self._persist.store(item)

    def recall(self, query: RecallQuery) -> list[MemoryItem]:
        """召回记忆条目"""
        items = list(self._items.values())

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

    def get_fact(self, key: str) -> Any | None:
        """获取单个事实"""
        for item in self._items.values():
            if item.content.get("key") == key:
                return item.content.get("value")
        return None

    def set_fact(self, key: str, value: Any, **kwargs) -> None:
        """设置单个事实"""
        # 查找已有的
        for item_id, item in self._items.items():
            if item.content.get("key") == key:
                item.content["value"] = value
                if self._persist:
                    self._persist.store(item)
                return

        # 创建新的
        self.store(MemoryItem(
            kind=MemoryKind.SEMANTIC,
            content={"key": key, "value": value, **kwargs},
            salience=kwargs.get("salience", 1.0),
            tags=kwargs.get("tags", []),
        ))


class PostgresSemanticBackend(BaseMemoryBackend):
    """PostgreSQL 持久化后端

    适用于需要跨会话持久化的语义记忆。
    """

    def __init__(
        self,
        connection_url: str,
        table_name: str = "harness_semantic_memory",
    ):
        """
        Args:
            connection_url: PostgreSQL 连接 URL
            table_name: 表名
        """
        self._url = connection_url
        self._table = table_name
        self._engine = None
        self._initialized = False

    def _ensure_initialized(self):
        """确保表已创建"""
        if self._initialized:
            return

        try:
            from sqlalchemy import Column, Float, String, Text, create_engine
            from sqlalchemy.dialects.postgresql import JSONB
            from sqlalchemy.orm import declarative_base

            self._engine = create_engine(self._url)
            Base = declarative_base()

            class SemanticMemoryTable(Base):
                __tablename__ = self._table

                id = Column(String(36), primary_key=True)
                content = Column(JSONB, nullable=False)
                salience = Column(Float, default=1.0)
                created_at = Column(Float)
                tags = Column(JSONB, default=[])
                source = Column(Text, nullable=True)

            Base.metadata.create_all(self._engine)
            self._table_class = SemanticMemoryTable
            self._initialized = True

        except ImportError:
            logger.warning("SQLAlchemy not installed, PostgresSemanticBackend disabled")
            raise

    def store(self, item: MemoryItem) -> None:
        """存储记忆条目"""
        self._ensure_initialized()

        from sqlalchemy.orm import Session

        with Session(self._engine) as session:
            row = self._table_class(
                id=item.item_id or str(uuid.uuid4()),
                content=item.content,
                salience=item.salience,
                created_at=item.created_at,
                tags=item.tags,
                source=item.source,
            )
            session.merge(row)
            session.commit()

    def recall(self, query: RecallQuery) -> list[MemoryItem]:
        """召回记忆条目"""
        self._ensure_initialized()

        from sqlalchemy.orm import Session

        with Session(self._engine) as session:
            rows = session.query(self._table_class).limit(query.limit).all()
            return [
                MemoryItem(
                    kind=MemoryKind.SEMANTIC,
                    content=row.content,
                    salience=row.salience,
                    created_at=row.created_at,
                    tags=row.tags or [],
                    source=row.source,
                    item_id=row.id,
                )
                for row in rows
            ]

    def clear(self) -> None:
        """清空所有记忆"""
        self._ensure_initialized()

        from sqlalchemy.orm import Session

        with Session(self._engine) as session:
            session.query(self._table_class).delete()
            session.commit()

    def delete(self, item_id: str) -> bool:
        """删除指定记忆"""
        self._ensure_initialized()

        from sqlalchemy.orm import Session

        with Session(self._engine) as session:
            result = session.query(self._table_class).filter_by(id=item_id).delete()
            session.commit()
            return result > 0
