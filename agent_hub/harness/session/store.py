"""会话存储"""

from __future__ import annotations

import logging
import threading
from typing import Any, Iterator

from agent_hub.harness.loop.machine import HarnessLoop
from agent_hub.harness.session.factory import SessionFactory

logger = logging.getLogger(__name__)


class SessionStore:
    """会话存储

    管理多个会话的生命周期。

    Features:
        - 线程安全的会话访问
        - 自动清理已终止的会话
        - 会话列表和状态查询

    Usage:
        store = SessionStore(factory)

        # 创建会话
        loop = store.create("session-1", role="backend")

        # 获取会话
        loop = store.get("session-1")

        # 执行
        result = loop.step({"message": "你好"})

        # 删除会话
        store.delete("session-1")
    """

    def __init__(self, factory: SessionFactory, max_sessions: int = 100):
        """
        Args:
            factory: 会话工厂
            max_sessions: 最大会话数
        """
        self._factory = factory
        self._max_sessions = max_sessions
        self._sessions: dict[str, HarnessLoop] = {}
        self._lock = threading.RLock()

    def create(self, session_id: str | None = None, **kwargs) -> HarnessLoop:
        """
        创建会话。

        Args:
            session_id: 会话 ID
            **kwargs: 会话参数

        Returns:
            HarnessLoop: 会话实例
        """
        with self._lock:
            # 检查容量
            if len(self._sessions) >= self._max_sessions:
                self._cleanup_halted()

            if len(self._sessions) >= self._max_sessions:
                raise RuntimeError(
                    f"Max sessions ({self._max_sessions}) reached. "
                    "Delete some sessions first."
                )

            loop = self._factory.build(session_id, **kwargs)
            actual_id = loop.state.session_id

            self._sessions[actual_id] = loop
            logger.info(
                "Created session: %s (total: %d)",
                actual_id,
                len(self._sessions),
            )

            return loop

    def get(self, session_id: str) -> HarnessLoop | None:
        """
        获取会话。

        Args:
            session_id: 会话 ID

        Returns:
            会话实例，如果不存在返回 None
        """
        with self._lock:
            return self._sessions.get(session_id)

    def get_or_create(self, session_id: str, **kwargs) -> HarnessLoop:
        """
        获取或创建会话。

        Args:
            session_id: 会话 ID
            **kwargs: 会话参数（仅创建时使用）

        Returns:
            HarnessLoop: 会话实例
        """
        with self._lock:
            if session_id in self._sessions:
                return self._sessions[session_id]
            return self.create(session_id, **kwargs)

    def delete(self, session_id: str) -> bool:
        """
        删除会话。

        Args:
            session_id: 会话 ID

        Returns:
            是否成功删除
        """
        with self._lock:
            if session_id in self._sessions:
                del self._sessions[session_id]
                logger.info(
                    "Deleted session: %s (remaining: %d)",
                    session_id,
                    len(self._sessions),
                )
                return True
            return False

    def has(self, session_id: str) -> bool:
        """检查会话是否存在"""
        with self._lock:
            return session_id in self._sessions

    def list(self) -> list[str]:
        """列出所有会话 ID"""
        with self._lock:
            return list(self._sessions.keys())

    def list_active(self) -> list[str]:
        """列出活跃会话（未终止）"""
        with self._lock:
            return [
                sid for sid, loop in self._sessions.items()
                if not loop.state.is_halted()
            ]

    def list_halted(self) -> list[str]:
        """列出已终止会话"""
        with self._lock:
            return [
                sid for sid, loop in self._sessions.items()
                if loop.state.is_halted()
            ]

    def count(self) -> int:
        """会话总数"""
        with self._lock:
            return len(self._sessions)

    def count_active(self) -> int:
        """活跃会话数"""
        with self._lock:
            return sum(
                1 for loop in self._sessions.values()
                if not loop.state.is_halted()
            )

    def get_status(self, session_id: str) -> dict[str, Any] | None:
        """
        获取会话状态。

        Args:
            session_id: 会话 ID

        Returns:
            状态信息，如果不存在返回 None
        """
        with self._lock:
            loop = self._sessions.get(session_id)
            if loop is None:
                return None
            return loop.get_summary()

    def get_all_status(self) -> dict[str, dict[str, Any]]:
        """获取所有会话状态"""
        with self._lock:
            return {
                sid: loop.get_summary()
                for sid, loop in self._sessions.items()
            }

    def _cleanup_halted(self) -> int:
        """清理已终止的会话"""
        halted = self.list_halted()
        for sid in halted:
            del self._sessions[sid]

        if halted:
            logger.info("Cleaned up %d halted sessions", len(halted))

        return len(halted)

    def cleanup(self, max_age_seconds: float | None = None) -> int:
        """
        清理会话。

        Args:
            max_age_seconds: 最大存活时间（秒），None 表示只清理已终止的

        Returns:
            清理的会话数
        """
        with self._lock:
            count = self._cleanup_halted()

            # TODO: 实现基于时间的清理
            # if max_age_seconds is not None:
            #     ...

            return count

    def clear(self) -> int:
        """清空所有会话"""
        with self._lock:
            count = len(self._sessions)
            self._sessions.clear()
            logger.info("Cleared all %d sessions", count)
            return count

    def __len__(self) -> int:
        return self.count()

    def __contains__(self, session_id: str) -> bool:
        return self.has(session_id)

    def __iter__(self) -> Iterator[str]:
        with self._lock:
            return iter(list(self._sessions.keys()))
