"""PEV 状态机核心实现"""

import logging
import time
from dataclasses import asdict
from typing import Any, Callable

from agent_hub.harness.loop.planner import Planner
from agent_hub.harness.loop.types import Bounds, HaltReason, LoopState, Phase, Plan
from agent_hub.harness.loop.verifier import Verifier

logger = logging.getLogger(__name__)


class HarnessLoop:
    """PEV 状态机

    实现 Plan-Execute-Verify 循环，提供可靠的任务执行框架。

    状态流转:
        IDLE → PLAN → EXECUTE → VERIFY → RESPOND → COMPACT → IDLE
                ↑                  ↓
                └──── replan ──────┘

    Features:
        - 边界约束：max_turns, max_replans, token_budget
        - 重规划机制：验证失败时自动重试
        - 状态转移钩子：可观测性支持
        - 上下文压缩：超阈值自动触发
    """

    def __init__(
        self,
        planner: Planner,
        verifier: Verifier,
        executor: Callable[[Plan, LoopState], dict[str, Any]],
        bounds: Bounds | None = None,
        on_transition: Callable[[Phase, Phase, LoopState], None] | None = None,
        on_error: Callable[[str, LoopState], None] | None = None,
        compactor: Callable[[LoopState], None] | None = None,
        token_counter: Callable[[LoopState], int] | None = None,
        session_id: str | None = None,
    ):
        """
        Args:
            planner: 规划器，生成执行计划
            verifier: 校验器，验证计划和结果
            executor: 执行器，执行计划并返回结果
            bounds: 边界约束
            on_transition: 状态转移回调
            on_error: 错误回调
            compactor: 上下文压缩器
            token_counter: Token 计数器
            session_id: 会话 ID
        """
        self.planner = planner
        self.verifier = verifier
        self.executor = executor
        self.bounds = bounds or Bounds()
        self.on_transition = on_transition
        self.on_error = on_error
        self.compactor = compactor
        self.token_counter = token_counter

        self.state = LoopState(session_id=session_id)

    def _to(self, phase: Phase) -> None:
        """状态转移"""
        old = self.state.phase
        self.state.phase = phase

        logger.debug(
            "Phase transition: %s -> %s (turn=%d, replan=%d)",
            old.name,
            phase.name,
            self.state.turn,
            self.state.replan_count,
        )

        if self.on_transition:
            self.on_transition(old, phase, self.state)

    def _halt(self, reason: HaltReason, message: str | None = None) -> None:
        """进入终止状态"""
        self.state.halt_reason = reason
        self.state.halt_message = message
        self._to(Phase.HALT)

        logger.info(
            "Loop halted: reason=%s, message=%s, turns=%d",
            reason.name,
            message,
            self.state.turn,
        )

    def _replan(self, reason: str) -> bool:
        """
        触发重规划。

        Returns:
            bool: 是否可以继续重规划
        """
        self.state.replan_count += 1
        self.state.record_error(reason)

        logger.warning(
            "Replan triggered: reason=%s, count=%d/%d",
            reason,
            self.state.replan_count,
            self.bounds.max_replans,
        )

        if self.on_error:
            self.on_error(reason, self.state)

        if self.state.replan_count > self.bounds.max_replans:
            self._halt(HaltReason.MAX_REPLANS, f"Max replans exceeded: {reason}")
            return False

        self._to(Phase.PLAN)
        return True

    def _check_bounds(self) -> bool:
        """检查边界约束"""
        if self.state.turn >= self.bounds.max_turns:
            self._halt(HaltReason.MAX_TURNS, f"Max turns ({self.bounds.max_turns}) reached")
            return False
        return True

    def _should_compact(self) -> bool:
        """检查是否需要压缩上下文"""
        if not self.token_counter or not self.compactor:
            return False

        tokens = self.token_counter(self.state)
        threshold = int(self.bounds.token_budget * self.bounds.compaction_ratio)
        return tokens > threshold

    def step(self, context: dict[str, Any]) -> dict[str, Any] | None:
        """
        执行一轮 PEV 循环。

        Args:
            context: 执行上下文（包含用户输入、记忆等）

        Returns:
            执行结果，如果已终止则返回 None
        """
        start_time = time.time()

        # 检查是否已终止
        if self.state.is_halted():
            logger.warning("Loop already halted: %s", self.state.halt_reason)
            return None

        # 边界检查
        if not self._check_bounds():
            return None

        try:
            result = self._execute_pev_cycle(context)
        except Exception as e:
            logger.exception("Execution error: %s", e)
            self.state.record_error(str(e))
            self._halt(HaltReason.ERROR, str(e))
            return None

        # 记录历史
        elapsed = time.time() - start_time
        self.state.record_history({
            "turn": self.state.turn,
            "plan": asdict(self.state.current_plan) if self.state.current_plan else None,
            "result": result,
            "elapsed_ms": int(elapsed * 1000),
        })

        return result

    def _execute_pev_cycle(self, context: dict[str, Any]) -> dict[str, Any] | None:
        """执行完整的 PEV 循环"""
        while True:
            # === PLAN ===
            self._to(Phase.PLAN)
            plan = self.planner.plan(self.state, context)
            self.state.current_plan = plan

            logger.debug("Plan generated: intent=%s, tools=%s", plan.intent, plan.tool_calls)

            # === VERIFY (plan) ===
            self._to(Phase.VERIFY)
            verify_result = self.verifier.verify_plan(plan, self.state)

            if not verify_result.passed:
                logger.warning("Plan verification failed: %s", verify_result.reason)
                if not self._replan(verify_result.reason or "Plan verification failed"):
                    return None
                # 将失败原因加入上下文供重规划参考
                context = {
                    **context,
                    "replan_reason": verify_result.reason,
                    "replan_suggestions": verify_result.suggestions,
                }
                continue

            # === EXECUTE ===
            self._to(Phase.EXECUTE)
            result = self.executor(plan, self.state)

            logger.debug("Execution completed: %s", result)

            # === VERIFY (result) ===
            self._to(Phase.VERIFY)
            verify_result = self.verifier.verify_result(result, plan, self.state)

            if not verify_result.passed:
                logger.warning("Result verification failed: %s", verify_result.reason)
                if not self._replan(verify_result.reason or "Result verification failed"):
                    return None
                context = {
                    **context,
                    "replan_reason": verify_result.reason,
                    "replan_suggestions": verify_result.suggestions,
                    "failed_result": result,
                }
                continue

            # === RESPOND ===
            self._to(Phase.RESPOND)
            self.state.turn += 1
            self.state.replan_count = 0  # 成功后重置

            # === COMPACT (conditional) ===
            if self._should_compact():
                self._to(Phase.COMPACT)
                self.compactor(self.state)
                logger.info("Context compacted at turn %d", self.state.turn)

            # 返回 IDLE
            self._to(Phase.IDLE)
            return result

    def run(
        self,
        initial_context: dict[str, Any],
        input_fn: Callable[[], dict[str, Any] | None],
        output_fn: Callable[[dict[str, Any]], None],
    ) -> None:
        """
        运行完整的交互循环。

        Args:
            initial_context: 初始上下文
            input_fn: 输入函数，返回 None 表示结束
            output_fn: 输出函数
        """
        context = initial_context

        while not self.state.is_halted():
            result = self.step(context)

            if result is None:
                break

            output_fn(result)

            # 获取下一轮输入
            next_input = input_fn()
            if next_input is None:
                self._halt(HaltReason.USER_ABORT, "User terminated")
                break

            context = {**context, **next_input}

    def reset(self) -> None:
        """重置状态机"""
        session_id = self.state.session_id
        self.state = LoopState(session_id=session_id)
        logger.info("Loop reset: session_id=%s", session_id)

    def get_summary(self) -> dict[str, Any]:
        """获取执行摘要"""
        return {
            "session_id": self.state.session_id,
            "phase": self.state.phase.name,
            "turn": self.state.turn,
            "halted": self.state.is_halted(),
            "halt_reason": self.state.halt_reason.name if self.state.halt_reason else None,
            "halt_message": self.state.halt_message,
            "error_count": len(self.state.errors),
            "last_errors": self.state.errors[-3:] if self.state.errors else [],
        }
