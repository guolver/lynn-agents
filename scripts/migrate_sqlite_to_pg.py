"""一次性迁移：SQLite (data/agent.db) → PostgreSQL。

用法（宿主机，激活 .venv）：
    DATABASE_URL=postgresql+psycopg://agent_hub:agent_hub@localhost:5432/agent_hub \
        python scripts/migrate_sqlite_to_pg.py

幂等可重跑：put 按 id upsert；单条失败记录并继续。
"""

from __future__ import annotations

import os
import sys

from agent_hub.agents.global_part_time.repository import SQLiteRepository
from agent_hub.database.repository import PostgresRepository

# 外键安全顺序：被引用者先行
KINDS = ["source", "job", "candidate", "match", "chat_session", "chat_message"]

DEFAULT_PG = "postgresql+psycopg://agent_hub:agent_hub@localhost:5432/agent_hub"


def main() -> int:
    sqlite_path = os.environ.get("SQLITE_PATH", "data/agent.db")
    pg_url = os.environ.get("DATABASE_URL", DEFAULT_PG)
    if not os.path.exists(sqlite_path):
        print(f"SQLite 文件不存在: {sqlite_path}")
        return 1

    src = SQLiteRepository(sqlite_path)
    dst = PostgresRepository(pg_url)

    failures: list[tuple[str, str, str]] = []
    for kind in KINDS:
        items = src.list(kind)
        migrated = 0
        for item in items:
            try:
                dst.put(kind, item)
                migrated += 1
            except Exception as exc:  # noqa: BLE001 - 单条失败不中断整体迁移
                failures.append((kind, str(item.get("id")), repr(exc)))
        print(f"{kind}: {migrated}/{len(items)} 迁移完成")

    if failures:
        print(f"\n失败 {len(failures)} 条：")
        for kind, item_id, err in failures:
            print(f"  [{kind}] {item_id}: {err}")
        return 2
    print("\n全部迁移成功。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
