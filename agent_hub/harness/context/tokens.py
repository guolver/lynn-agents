"""Token 估算工具"""

import logging
from typing import Any, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


def estimate_tokens(text: str, model: str = "gpt-4") -> int:
    """
    估算文本的 Token 数量。

    使用简单的字符比例估算，或 tiktoken（如果可用）。

    Args:
        text: 文本内容
        model: 模型名称

    Returns:
        估算的 Token 数
    """
    try:
        import tiktoken

        encoding = tiktoken.encoding_for_model(model)
        return len(encoding.encode(text))
    except ImportError:
        # 简单估算：英文约 4 字符/token，中文约 1.5 字符/token
        chinese_chars = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
        other_chars = len(text) - chinese_chars

        chinese_tokens = chinese_chars / 1.5
        other_tokens = other_chars / 4

        return int(chinese_tokens + other_tokens)
    except Exception as e:
        logger.warning("Token estimation failed: %s, using fallback", e)
        return len(text) // 4


def estimate_messages_tokens(messages: list[dict[str, Any]], model: str = "gpt-4") -> int:
    """
    估算消息列表的 Token 数量。

    Args:
        messages: 消息列表
        model: 模型名称

    Returns:
        估算的 Token 数
    """
    total = 0

    for message in messages:
        # 每条消息有固定开销
        total += 4  # <im_start>, role, \n, <im_end>

        content = message.get("content", "")
        if isinstance(content, str):
            total += estimate_tokens(content, model)
        elif isinstance(content, list):
            # 多模态内容
            for part in content:
                if isinstance(part, dict) and "text" in part:
                    total += estimate_tokens(part["text"], model)

        # Function call 额外开销
        if "function_call" in message:
            fc = message["function_call"]
            total += estimate_tokens(fc.get("name", ""), model)
            total += estimate_tokens(fc.get("arguments", ""), model)

    # 消息列表结尾开销
    total += 2

    return total


@runtime_checkable
class TokenCounter(Protocol):
    """Token 计数器协议"""

    def count(self, text: str) -> int:
        """计算文本 Token 数"""
        ...

    def count_messages(self, messages: list[dict[str, Any]]) -> int:
        """计算消息 Token 数"""
        ...


class SimpleTokenCounter:
    """简单 Token 计数器"""

    def __init__(self, model: str = "gpt-4"):
        self._model = model

    def count(self, text: str) -> int:
        return estimate_tokens(text, self._model)

    def count_messages(self, messages: list[dict[str, Any]]) -> int:
        return estimate_messages_tokens(messages, self._model)


class TiktokenCounter:
    """基于 tiktoken 的 Token 计数器"""

    def __init__(self, model: str = "gpt-4"):
        import tiktoken

        self._encoding = tiktoken.encoding_for_model(model)

    def count(self, text: str) -> int:
        return len(self._encoding.encode(text))

    def count_messages(self, messages: list[dict[str, Any]]) -> int:
        total = 0

        for message in messages:
            total += 4
            content = message.get("content", "")
            if isinstance(content, str):
                total += len(self._encoding.encode(content))

        total += 2
        return total
