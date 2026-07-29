"""上下文压缩管道"""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from agent_hub.harness.context.tokens import estimate_tokens

logger = logging.getLogger(__name__)


@runtime_checkable
class ModelClient(Protocol):
    """模型客户端协议"""

    def chat(self, messages: list[dict[str, str]]) -> str:
        ...


@dataclass
class CompactionResult:
    """压缩结果"""

    messages: list[dict[str, Any]]
    """压缩后的消息列表"""

    summary: str | None = None
    """生成的摘要"""

    original_tokens: int = 0
    """原始 Token 数"""

    compressed_tokens: int = 0
    """压缩后 Token 数"""

    layers_applied: list[str] = None
    """应用的压缩层"""

    def __post_init__(self):
        if self.layers_applied is None:
            self.layers_applied = []

    @property
    def compression_ratio(self) -> float:
        """压缩率"""
        if self.original_tokens == 0:
            return 0.0
        return 1.0 - (self.compressed_tokens / self.original_tokens)


class CompactionLayer(ABC):
    """压缩层基类"""

    name: str = "base"

    @abstractmethod
    def compact(
        self,
        messages: list[dict[str, Any]],
        target_tokens: int,
    ) -> list[dict[str, Any]]:
        """
        执行压缩。

        Args:
            messages: 待压缩的消息列表
            target_tokens: 目标 Token 数

        Returns:
            压缩后的消息列表
        """
        ...


class RollingWindowLayer(CompactionLayer):
    """滚动窗口截断层

    保留最近 N 轮消息，截断早期内容。
    """

    name = "rolling_window"

    def __init__(self, max_turns: int = 10):
        self._max_turns = max_turns

    def compact(
        self,
        messages: list[dict[str, Any]],
        target_tokens: int,
    ) -> list[dict[str, Any]]:
        # 找到 system 消息
        system_messages = [m for m in messages if m.get("role") == "system"]
        other_messages = [m for m in messages if m.get("role") != "system"]

        # 保留最近的消息
        kept_messages = other_messages[-self._max_turns * 2:]

        result = system_messages + kept_messages

        logger.debug(
            "RollingWindow: %d -> %d messages",
            len(messages),
            len(result),
        )

        return result


class MessageMergingLayer(CompactionLayer):
    """消息合并层

    合并相邻的同角色消息。
    """

    name = "message_merging"

    def compact(
        self,
        messages: list[dict[str, Any]],
        target_tokens: int,
    ) -> list[dict[str, Any]]:
        if not messages:
            return messages

        result = []
        current = None

        for msg in messages:
            if current is None:
                current = msg.copy()
            elif msg.get("role") == current.get("role"):
                # 合并内容
                current["content"] = (
                    current.get("content", "") + "\n\n" + msg.get("content", "")
                )
            else:
                result.append(current)
                current = msg.copy()

        if current:
            result.append(current)

        logger.debug(
            "MessageMerging: %d -> %d messages",
            len(messages),
            len(result),
        )

        return result


class ToolOutputSummarizationLayer(CompactionLayer):
    """工具输出摘要化层

    将详细的工具输出压缩为摘要。
    """

    name = "tool_output_summarization"

    def __init__(self, max_output_length: int = 500):
        self._max_length = max_output_length

    def compact(
        self,
        messages: list[dict[str, Any]],
        target_tokens: int,
    ) -> list[dict[str, Any]]:
        result = []

        for msg in messages:
            if msg.get("role") == "tool" or msg.get("role") == "function":
                content = msg.get("content", "")
                if len(content) > self._max_length:
                    # 截断工具输出
                    truncated = content[:self._max_length] + "...[truncated]"
                    msg = {**msg, "content": truncated}

            result.append(msg)

        return result


class KeywordExtractionLayer(CompactionLayer):
    """关键词提取层

    从被截断的内容中提取关键信息。
    """

    name = "keyword_extraction"

    def __init__(self, model_client: ModelClient | None = None):
        self._model = model_client

    def compact(
        self,
        messages: list[dict[str, Any]],
        target_tokens: int,
    ) -> list[dict[str, Any]]:
        # 如果没有模型，跳过
        if not self._model:
            return messages

        # 找到较长的消息进行提取
        result = []
        for msg in messages:
            content = msg.get("content", "")
            if len(content) > 1000 and msg.get("role") != "system":
                # 提取关键信息
                extracted = self._extract_keywords(content)
                msg = {**msg, "content": extracted}

            result.append(msg)

        return result

    def _extract_keywords(self, content: str) -> str:
        """提取关键信息"""
        prompt = f"""请提取以下内容的关键信息，保留重要的事实和数据，删除冗余：

{content}

只输出提取后的内容，不要添加任何解释。"""

        try:
            response = self._model.chat([
                {"role": "user", "content": prompt},
            ])
            return response
        except Exception as e:
            logger.warning("Keyword extraction failed: %s", e)
            return content[:500] + "...[summarized]"


class FullContextRewriteLayer(CompactionLayer):
    """完整上下文重写层

    使用 LLM 重写整个上下文（最后手段）。
    """

    name = "full_context_rewrite"

    def __init__(self, model_client: ModelClient):
        self._model = model_client

    def compact(
        self,
        messages: list[dict[str, Any]],
        target_tokens: int,
    ) -> list[dict[str, Any]]:
        # 提取系统消息
        system_msg = next(
            (m for m in messages if m.get("role") == "system"),
            None,
        )

        # 构建要重写的内容
        content_to_rewrite = "\n\n".join(
            f"[{m.get('role')}]: {m.get('content', '')}"
            for m in messages
            if m.get("role") != "system"
        )

        prompt = f"""请将以下对话内容压缩为简洁的摘要，保留所有重要信息和决策：

{content_to_rewrite}

目标：压缩到约 {target_tokens // 4} 个词以内。
输出格式：简洁的摘要文本。"""

        try:
            summary = self._model.chat([
                {"role": "user", "content": prompt},
            ])

            result = []
            if system_msg:
                result.append(system_msg)

            result.append({
                "role": "user",
                "content": f"## 历史摘要\n{summary}",
            })

            logger.info(
                "FullContextRewrite: %d tokens -> ~%d tokens",
                estimate_tokens(content_to_rewrite),
                estimate_tokens(summary),
            )

            return result

        except Exception as e:
            logger.error("Full context rewrite failed: %s", e)
            return messages


class CompactionPipeline:
    """压缩管道

    按顺序执行多个压缩层，直到达到目标 Token 数。

    Pipeline Order:
        1. Tool Output Summarization
        2. Rolling Window
        3. Keyword Extraction
        4. Message Merging
        5. Full Context Rewrite (optional)
    """

    def __init__(
        self,
        model_client: ModelClient | None = None,
        layers: list[CompactionLayer] | None = None,
    ):
        """
        Args:
            model_client: LLM 客户端（用于高级压缩）
            layers: 自定义压缩层列表
        """
        self._model = model_client

        if layers is not None:
            self._layers = layers
        else:
            self._layers = self._default_layers()

    def _default_layers(self) -> list[CompactionLayer]:
        """默认压缩层"""
        layers = [
            ToolOutputSummarizationLayer(),
            RollingWindowLayer(max_turns=15),
            MessageMergingLayer(),
        ]

        if self._model:
            layers.append(KeywordExtractionLayer(self._model))

        return layers

    def compact(
        self,
        messages: list[dict[str, Any]],
        target_tokens: int,
    ) -> CompactionResult:
        """
        执行压缩。

        Args:
            messages: 待压缩的消息列表
            target_tokens: 目标 Token 数

        Returns:
            CompactionResult: 压缩结果
        """
        original_tokens = self._count_tokens(messages)
        current_messages = messages
        layers_applied = []

        for layer in self._layers:
            current_tokens = self._count_tokens(current_messages)

            if current_tokens <= target_tokens:
                break

            logger.debug(
                "Applying layer %s: %d tokens, target %d",
                layer.name,
                current_tokens,
                target_tokens,
            )

            current_messages = layer.compact(current_messages, target_tokens)
            layers_applied.append(layer.name)

        # 最后手段：完整重写
        final_tokens = self._count_tokens(current_messages)
        if final_tokens > target_tokens and self._model:
            rewrite_layer = FullContextRewriteLayer(self._model)
            current_messages = rewrite_layer.compact(current_messages, target_tokens)
            layers_applied.append(rewrite_layer.name)

        return CompactionResult(
            messages=current_messages,
            original_tokens=original_tokens,
            compressed_tokens=self._count_tokens(current_messages),
            layers_applied=layers_applied,
        )

    def _count_tokens(self, messages: list[dict[str, Any]]) -> int:
        """计算消息 Token 数"""
        total = 0
        for msg in messages:
            content = msg.get("content", "")
            if isinstance(content, str):
                total += estimate_tokens(content) + 4
        return total

    def add_layer(self, layer: CompactionLayer) -> "CompactionPipeline":
        """添加压缩层"""
        self._layers.append(layer)
        return self

    def insert_layer(self, index: int, layer: CompactionLayer) -> "CompactionPipeline":
        """插入压缩层"""
        self._layers.insert(index, layer)
        return self
