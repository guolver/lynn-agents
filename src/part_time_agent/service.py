"""兼容旧服务导入；新代码请使用 agent_hub 包。"""

from agent_hub.agents.global_part_time.service import AgentService, NotFoundError, PolicyError

__all__ = ["AgentService", "NotFoundError", "PolicyError"]

