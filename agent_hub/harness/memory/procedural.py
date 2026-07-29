"""程序记忆实现"""

import logging
import uuid
from pathlib import Path
from typing import Any

from agent_hub.harness.memory.base import BaseMemoryBackend
from agent_hub.harness.memory.types import MemoryItem, MemoryKind, RecallQuery

logger = logging.getLogger(__name__)


class ProceduralMemory(BaseMemoryBackend):
    """程序记忆

    规则和约束，静态配置。通常从配置文件加载，运行时只读。

    Features:
        - 基于 ID 的规则索引
        - 不可变（只读）
        - 支持规则优先级
    """

    def __init__(self, rules: list[dict[str, Any]] | None = None):
        """
        Args:
            rules: 初始规则列表
        """
        self._items: dict[str, MemoryItem] = {}

        if rules:
            for rule in rules:
                self._add_rule(rule)

    def _add_rule(self, rule: dict[str, Any]) -> None:
        """添加规则"""
        item_id = rule.get("id") or str(uuid.uuid4())
        item = MemoryItem(
            kind=MemoryKind.PROCEDURAL,
            content=rule,
            salience=rule.get("priority", 1.0),
            tags=rule.get("tags", []),
            source="config",
            item_id=item_id,
        )
        self._items[item_id] = item

    def store(self, item: MemoryItem) -> None:
        """存储规则（通常不使用）"""
        if item.item_id is None:
            item.item_id = str(uuid.uuid4())
        self._items[item.item_id] = item

    def recall(self, query: RecallQuery) -> list[MemoryItem]:
        """召回规则"""
        items = list(self._items.values())

        if query.filters:
            items = self._apply_filters(items, query.filters)

        return items

    def clear(self) -> None:
        """清空所有规则"""
        self._items.clear()

    def delete(self, item_id: str) -> bool:
        """删除指定规则"""
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

    def get_rule(self, rule_id: str) -> dict[str, Any] | None:
        """获取单个规则"""
        item = self._items.get(rule_id)
        return item.content if item else None

    def get_rules_by_tag(self, tag: str) -> list[dict[str, Any]]:
        """按标签获取规则"""
        return [
            item.content
            for item in self._items.values()
            if tag in item.tags
        ]


class YamlProceduralBackend(ProceduralMemory):
    """YAML 配置文件后端

    从 YAML 文件加载规则配置。

    Expected format:
        rules:
          - id: rule1
            desc: "描述"
            priority: 1.0
            tags: ["tag1", "tag2"]
            condition: "..."
            action: "..."
    """

    def __init__(self, path: Path | str):
        """
        Args:
            path: YAML 配置文件路径
        """
        super().__init__()
        self._path = Path(path)
        self._load()

    def _load(self) -> None:
        """加载配置文件"""
        if not self._path.exists():
            logger.warning("Procedural config not found: %s", self._path)
            return

        try:
            import yaml

            with open(self._path, encoding="utf-8") as f:
                data = yaml.safe_load(f)

            rules = data.get("rules", [])
            for rule in rules:
                self._add_rule(rule)

            # 也支持顶层的 bounds 和 global_rules
            if "bounds" in data:
                self._add_rule({
                    "id": "bounds",
                    "type": "bounds",
                    **data["bounds"],
                })

            if "global_rules" in data:
                for rule in data["global_rules"]:
                    self._add_rule({
                        "type": "global",
                        **rule,
                    })

            logger.info("Loaded %d procedural rules from %s", len(self._items), self._path)

        except ImportError:
            logger.error("PyYAML not installed, cannot load procedural config")
        except Exception as e:
            logger.error("Failed to load procedural config: %s", e)

    def reload(self) -> None:
        """重新加载配置"""
        self.clear()
        self._load()
