"""兼容 ``uvicorn part_time_agent.api:app`` 启动命令。"""

from agent_hub.app import app, create_app

__all__ = ["app", "create_app"]

