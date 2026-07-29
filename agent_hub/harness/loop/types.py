"""PEV 状态机类型定义"""

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any


class Phase(Enum):
    """状态机阶段"""

    IDLE = auto()  # 空闲，等待输入
    PLAN = auto()  # 规划阶段
    EXECUTE = auto()  # 执行阶段
    VERIFY = auto()  # 校验阶段
    RESPOND = auto()  # 响应阶段
    COMPACT = auto()  # 压缩阶段
    HALT = auto()  # 终止状态


class HaltReason(Enum):
    """终止原因"""

    COMPLETED = auto()  # 正常完成
    MAX_TURNS = auto()  # 超过最大轮次
    MAX_REPLANS = auto()  # 超过最大重规划次数
    ERROR = auto()  # 执行错误
    USER_ABORT = auto()  # 用户中止


@dataclass
class Bounds:
    """执行边界约束"""

    max_turns: int = 30
    """最大轮次数"""

    max_replans: int = 3
    """单轮最大重规划次数"""

    max_tool_calls_per_turn: int = 5
    """单轮最大工具调用次数"""

    token_budget: int = 24000
    """Token 预算"""

    compaction_ratio: float = 0.85
    """压缩触发阈值（超过 budget * ratio 时触发）"""

    single_output_cap: int = 500
    """单次输出 Token 上限"""


@dataclass
class Plan:
    """规划输出"""

    intent: str
    """意图标识（如 ask, grade, search, finish）"""

    tool_calls: list[str] = field(default_factory=list)
    """本轮计划调用的工具列表"""

    subagent: str | None = None
    """委托执行的子 Agent 名称"""

    query: str | None = None
    """检索 query（如适用）"""

    metadata: dict[str, Any] = field(default_factory=dict)
    """附加元数据"""

    def __post_init__(self):
        if self.tool_calls is None:
            self.tool_calls = []
        if self.metadata is None:
            self.metadata = {}


@dataclass
class VerifyResult:
    """校验结果"""

    passed: bool
    """是否通过校验"""

    reason: str | None = None
    """失败原因（如有）"""

    suggestions: list[str] = field(default_factory=list)
    """改进建议"""

    @classmethod
    def ok(cls) -> "VerifyResult":
        return cls(passed=True)

    @classmethod
    def fail(cls, reason: str, suggestions: list[str] | None = None) -> "VerifyResult":
        return cls(passed=False, reason=reason, suggestions=suggestions or [])


@dataclass
class LoopState:
    """状态机状态"""

    phase: Phase = Phase.IDLE
    """当前阶段"""

    turn: int = 0
    """已执行轮次"""

    replan_count: int = 0
    """当前轮重规划次数"""

    history: list[dict[str, Any]] = field(default_factory=list)
    """执行历史"""

    errors: list[str] = field(default_factory=list)
    """错误记录"""

    halt_reason: HaltReason | None = None
    """终止原因"""

    halt_message: str | None = None
    """终止消息"""

    current_plan: Plan | None = None
    """当前规划"""

    session_id: str | None = None
    """会话 ID"""

    metadata: dict[str, Any] = field(default_factory=dict)
    """会话级元数据"""

    def is_halted(self) -> bool:
        return self.phase == Phase.HALT

    def record_error(self, error: str) -> None:
        self.errors.append(error)

    def record_history(self, entry: dict[str, Any]) -> None:
        self.history.append(entry)
