"""工具规约定义"""

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class ToolParameter:
    """工具参数定义"""

    name: str
    """参数名"""

    type: str
    """参数类型（str, int, float, bool, list, dict）"""

    description: str = ""
    """参数描述"""

    required: bool = True
    """是否必填"""

    default: Any = None
    """默认值"""

    enum: list[Any] | None = None
    """枚举值（如果有）"""

    def to_dict(self) -> dict[str, Any]:
        """转换为 JSON Schema 格式"""
        result = {
            "type": self._map_type(),
            "description": self.description,
        }

        if self.enum:
            result["enum"] = self.enum

        return result

    def _map_type(self) -> str:
        """映射到 JSON Schema 类型"""
        mapping = {
            "str": "string",
            "string": "string",
            "int": "integer",
            "integer": "integer",
            "float": "number",
            "number": "number",
            "bool": "boolean",
            "boolean": "boolean",
            "list": "array",
            "array": "array",
            "dict": "object",
            "object": "object",
        }
        return mapping.get(self.type.lower(), "string")


@dataclass
class ToolSpec:
    """工具规约

    描述工具的元数据，用于 LLM 理解和调用。
    """

    name: str
    """工具名称"""

    description: str
    """工具描述"""

    parameters: dict[str, dict[str, Any]] = field(default_factory=dict)
    """参数定义

    格式: {
        "param_name": {
            "type": "str",
            "required": True,
            "description": "..."
        }
    }
    """

    returns: str = ""
    """返回值描述"""

    examples: list[dict[str, Any]] = field(default_factory=list)
    """使用示例"""

    tags: list[str] = field(default_factory=list)
    """标签（用于分类）"""

    def required_params(self) -> list[str]:
        """获取必填参数列表"""
        return [
            name for name, spec in self.parameters.items()
            if spec.get("required", True)
        ]

    def optional_params(self) -> list[str]:
        """获取可选参数列表"""
        return [
            name for name, spec in self.parameters.items()
            if not spec.get("required", True)
        ]

    def to_openai_function(self) -> dict[str, Any]:
        """转换为 OpenAI Function Calling 格式"""
        properties = {}
        required = []

        for name, spec in self.parameters.items():
            prop = {
                "type": self._map_type(spec.get("type", "string")),
                "description": spec.get("description", ""),
            }

            if "enum" in spec:
                prop["enum"] = spec["enum"]

            properties[name] = prop

            if spec.get("required", True):
                required.append(name)

        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        }

    def _map_type(self, type_str: str) -> str:
        """映射类型"""
        mapping = {
            "str": "string",
            "string": "string",
            "int": "integer",
            "integer": "integer",
            "float": "number",
            "number": "number",
            "bool": "boolean",
            "boolean": "boolean",
            "list": "array",
            "array": "array",
            "dict": "object",
            "object": "object",
        }
        return mapping.get(type_str.lower(), "string")


@dataclass
class Tool:
    """工具实例

    封装工具规约和实现函数。
    """

    spec: ToolSpec
    """工具规约"""

    func: Callable[..., Any]
    """实现函数"""

    def __call__(self, **kwargs) -> Any:
        """调用工具"""
        # 校验必填参数
        missing = []
        for name in self.spec.required_params():
            if name not in kwargs:
                missing.append(name)

        if missing:
            raise ValueError(f"Missing required parameters: {missing}")

        # 应用默认值
        for name, param_spec in self.spec.parameters.items():
            if name not in kwargs and "default" in param_spec:
                kwargs[name] = param_spec["default"]

        return self.func(**kwargs)

    @property
    def name(self) -> str:
        return self.spec.name

    @property
    def description(self) -> str:
        return self.spec.description
