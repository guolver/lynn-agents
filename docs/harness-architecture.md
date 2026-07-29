# Harness 架构设计文档

## 概述

Harness 是 Agent Hub 平台的核心执行框架，提供 **PEV 状态机**、**子 Agent 隔离**、**分层记忆** 和 **上下文压缩** 等能力。它作为可选的增强层，让 Agent 能够处理复杂的多轮对话、长上下文任务和需要规划-验证的工作流。

## 设计目标

| 目标 | 描述 |
|-----|------|
| **可靠性** | 通过 PEV 循环和重规划机制保证任务完成 |
| **隔离性** | 子 Agent 权限白名单 + 历史隔离，防止上下文污染 |
| **可观测性** | 完整的状态转移记录和事件日志 |
| **可扩展性** | 插件式工具注册、可替换的 Planner/Verifier |
| **渐进引入** | 各模块独立，现有 Agent 可按需采用 |

## 架构总览

```
┌─────────────────────────────────────────────────────────────────┐
│                         Agent Hub                                │
├─────────────────────────────────────────────────────────────────┤
│  core/                          │  harness/                      │
│  ├── contracts.py (Protocol)   │  ├── loop/     (PEV 状态机)    │
│  ├── registry.py  (注册表)      │  ├── subagent/ (子 Agent)      │
│  └── security.py  (RBAC)       │  ├── memory/   (分层记忆)      │
│                                 │  ├── context/  (上下文压缩)    │
│                                 │  ├── tools/    (工具注册表)    │
│                                 │  └── session/  (会话工厂)      │
├─────────────────────────────────────────────────────────────────┤
│  agents/                                                         │
│  ├── global_part_time/  (现有 Agent，可选用 Harness)             │
│  └── mock_interview/    (可升级为 Harness 模式)                  │
└─────────────────────────────────────────────────────────────────┘
```

## 目录结构

```
agent_hub/harness/
├── __init__.py
├── loop/                       # PEV 状态机
│   ├── __init__.py
│   ├── machine.py              # HarnessLoop 核心状态机
│   ├── types.py                # Phase, LoopState, Plan, Bounds
│   ├── planner.py              # Planner 协议与实现
│   └── verifier.py             # Verifier 协议与实现
│
├── subagent/                   # 子 Agent 隔离框架
│   ├── __init__.py
│   ├── base.py                 # SubAgent 基类
│   ├── registry.py             # SubAgent 注册表
│   └── types.py                # SubTask, SubResult
│
├── memory/                     # 分层记忆系统
│   ├── __init__.py
│   ├── base.py                 # MemoryService 编排器
│   ├── working.py              # WorkingMemory 实现
│   ├── episodic.py             # EpisodicMemory 实现
│   ├── semantic.py             # SemanticMemory 实现
│   ├── procedural.py           # ProceduralMemory 实现
│   └── types.py                # MemoryItem, MemoryKind, RecallQuery
│
├── context/                    # 上下文管理
│   ├── __init__.py
│   ├── assembler.py            # ContextAssembler 组装器
│   ├── compaction.py           # 五层压缩管道
│   └── tokens.py               # Token 估算工具
│
├── tools/                      # 工具系统
│   ├── __init__.py
│   ├── registry.py             # ToolRegistry 注册表
│   ├── spec.py                 # ToolSpec, Tool 定义
│   └── builtin.py              # 内置工具集
│
└── session/                    # 会话管理
    ├── __init__.py
    ├── factory.py              # SessionFactory 工厂
    └── store.py                # SessionStore 存储
```

---

## 核心模块

### 1. PEV 状态机 (`harness/loop/`)

PEV（Plan-Execute-Verify）状态机是 Harness 的核心，保证任务执行的可靠性和可观测性。

#### 状态流转

```
     ┌──────────────────────────────────────────────────┐
     │                                                  │
     ▼                                                  │
   IDLE ──▶ PLAN ──▶ EXECUTE ──▶ VERIFY ──▶ RESPOND ──▶ COMPACT
     │        │                    │                      │
     │        │                    │                      │
     │        └────── replan ◀─────┘                      │
     │                  │                                 │
     │                  ▼                                 │
     │            max_replans?                            │
     │                  │                                 │
     │                  ▼                                 │
     └──────────────▶ HALT ◀──────────────────────────────┘
```

| 阶段 | 职责 |
|-----|------|
| **IDLE** | 空闲状态，等待输入 |
| **PLAN** | 规划本轮动作，生成 Plan 对象 |
| **EXECUTE** | 执行 Plan，调用子 Agent 或工具 |
| **VERIFY** | 校验执行结果，失败则触发重规划 |
| **RESPOND** | 准备响应，更新状态 |
| **COMPACT** | 上下文压缩（超阈值时触发） |
| **HALT** | 终止状态（完成/超限/错误） |

#### 核心类型

```python
class Phase(Enum):
    IDLE = auto()
    PLAN = auto()
    EXECUTE = auto()
    VERIFY = auto()
    RESPOND = auto()
    COMPACT = auto()
    HALT = auto()

@dataclass
class Bounds:
    """执行边界约束"""
    max_turns: int = 30              # 最大轮次
    max_replans: int = 3             # 单轮最大重规划次数
    max_tool_calls_per_turn: int = 5 # 单轮最大工具调用
    token_budget: int = 24000        # Token 预算
    compaction_ratio: float = 0.85   # 压缩触发阈值

@dataclass
class Plan:
    """规划输出"""
    intent: str                      # 意图标识 (ask/grade/search/finish)
    tool_calls: list[str]            # 本轮工具调用列表
    subagent: str | None = None      # 委托的子 Agent
    query: str | None = None         # 检索 query
    metadata: dict = field(default_factory=dict)

@dataclass
class LoopState:
    """状态机状态"""
    phase: Phase = Phase.IDLE
    turn: int = 0
    replan_count: int = 0
    history: list[dict] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    halt_reason: str | None = None
```

#### 使用示例

```python
from agent_hub.harness.loop import HarnessLoop, Bounds

loop = HarnessLoop(
    planner=my_planner,
    verifier=my_verifier,
    executor=my_executor,
    bounds=Bounds(max_turns=20, max_replans=3),
    on_transition=lambda old, new, state: print(f"{old} -> {new}")
)

# 执行一轮
result = loop.step(context={"message": "用户输入"})

# 检查状态
if loop.state.phase == Phase.HALT:
    print(f"已终止: {loop.state.halt_reason}")
```

#### 重规划机制

当 Verify 阶段校验失败时，状态机会：

1. 记录错误原因到 `state.errors`
2. 增加 `state.replan_count`
3. 检查是否超过 `bounds.max_replans`
4. 未超限则返回 PLAN 阶段重新规划
5. 超限则进入 HALT 状态

```python
def _replan(self, reason: str) -> bool:
    self.state.replan_count += 1
    self.state.errors.append(reason)

    if self.state.replan_count > self.bounds.max_replans:
        self._halt(f"max_replans_exceeded: {reason}")
        return False

    self._to(Phase.PLAN)
    return True
```

---

### 2. 子 Agent 隔离框架 (`harness/subagent/`)

子 Agent 框架提供权限隔离和上下文隔离，防止子任务污染主上下文。

#### 设计原则

| 原则 | 实现 |
|-----|------|
| **权限白名单** | 每个子 Agent 声明 `allowed_tools`，运行时强制检查 |
| **历史隔离** | 子 Agent 有独立的 `_history`，执行后清空 |
| **输出摘要** | 只返回 `SubResult.summary`，不回传完整历史 |
| **显式输入** | 通过 `SubTask.inputs` 传递，非共享内存 |

#### 核心类型

```python
@dataclass
class SubTask:
    """子任务输入"""
    goal: str                        # 任务目标描述
    inputs: dict                     # 显式输入参数
    max_tool_calls: int = 5          # 工具调用上限

@dataclass
class SubResult:
    """子任务输出"""
    summary: str                     # 回传主上下文的摘要
    structured: dict                 # 结构化输出（JSON 可解析）
    tokens_used: int = 0
    tool_calls_made: int = 0
```

#### SubAgent 基类

```python
class SubAgent(ABC):
    """子 Agent 基类"""

    # 子类必须声明允许的工具
    allowed_tools: frozenset[str] = frozenset()

    def __init__(self, model_client, tool_registry):
        self._model = model_client
        self._tools = tool_registry
        self._history: list[dict] = []  # 隔离历史

    def execute(self, task: SubTask) -> SubResult:
        """执行子任务"""
        self._history.clear()
        result = self._run(task)
        self._history.clear()  # 销毁历史
        return result

    @abstractmethod
    def _run(self, task: SubTask) -> SubResult:
        """子类实现"""
        ...

    def _call_tool(self, name: str, **kwargs) -> Any:
        """权限检查后调用工具"""
        if name not in self.allowed_tools:
            raise ToolPermissionError(
                f"Tool '{name}' not allowed. Allowed: {self.allowed_tools}"
            )
        return self._tools.call(name, **kwargs)
```

#### 实现示例

```python
class ExaminerAgent(SubAgent):
    """出题官子 Agent"""

    allowed_tools = frozenset(["search_questions", "lookup_jd"])

    def _run(self, task: SubTask) -> SubResult:
        # 构建提示词
        prompt = f"""
        你是出题官。根据以下信息出一道面试题：
        - 岗位: {task.inputs['role']}
        - 主题: {task.inputs['topic']}
        - 难度: {task.inputs['difficulty']}
        """

        # 搜索题库
        questions = self._call_tool(
            "search_questions",
            role=task.inputs['role'],
            topic=task.inputs['topic']
        )

        # 调用模型生成
        reply = self._ask_model([
            {"role": "system", "content": prompt},
            {"role": "user", "content": f"参考题库: {questions}"}
        ])

        # 解析结构化输出
        structured = json.loads(reply)

        return SubResult(
            summary=f"已生成关于{task.inputs['topic']}的面试题",
            structured=structured,
            tokens_used=self._count_tokens()
        )
```

---

### 3. 分层记忆系统 (`harness/memory/`)

四层记忆系统管理不同生命周期和用途的信息。

#### 记忆层级

```
┌─────────────────────────────────────────────────────────────┐
│                     MemoryService                            │
├─────────────────────────────────────────────────────────────┤
│  ┌───────────┐  ┌───────────┐  ┌───────────┐  ┌───────────┐ │
│  │  WORKING  │  │ EPISODIC  │  │ SEMANTIC  │  │PROCEDURAL │ │
│  │           │  │           │  │           │  │           │ │
│  │ 当前轮次   │  │  历史事件  │  │  事实知识  │  │  规则约束  │ │
│  │ 易失性    │  │  可持久化  │  │  可持久化  │  │  静态配置  │ │
│  └─────┬─────┘  └─────┬─────┘  └─────┬─────┘  └───────────┘ │
│        │              │              │                       │
│        └──── promote ─┴── promote ───┘                       │
└─────────────────────────────────────────────────────────────┘
```

| 层级 | 用途 | 生命周期 | 示例 |
|-----|------|---------|------|
| **Working** | 当前轮次的临时信息 | 轮次结束后清空 | 当前问题、用户最新回答 |
| **Episodic** | 历史事件和交互记录 | 会话级持久化 | 已问过的题目、评分记录 |
| **Semantic** | 事实性知识和画像 | 跨会话持久化 | 用户画像、岗位要求 |
| **Procedural** | 规则和约束 | 静态配置 | 评分标准、出题规则 |

#### 核心类型

```python
class MemoryKind(Enum):
    WORKING = auto()
    EPISODIC = auto()
    SEMANTIC = auto()
    PROCEDURAL = auto()

@dataclass
class MemoryItem:
    kind: MemoryKind
    content: dict
    salience: float = 1.0            # 显著性分数
    created_at: float = field(default_factory=time.time)

    def effective_salience(self, decay_rate: float = 0.1) -> float:
        """计算时间衰减后的显著性"""
        age = time.time() - self.created_at
        return self.salience * (1.0 / (1.0 + decay_rate * age))

@dataclass
class RecallQuery:
    kinds: list[MemoryKind]          # 查询的记忆层级
    filters: dict = field(default_factory=dict)
    limit: int = 10
```

#### MemoryService 编排器

```python
class MemoryService:
    def __init__(
        self,
        working: MemoryBackend,
        episodic: MemoryBackend,
        semantic: MemoryBackend,
        procedural: MemoryBackend,
    ):
        self._backends = {
            MemoryKind.WORKING: working,
            MemoryKind.EPISODIC: episodic,
            MemoryKind.SEMANTIC: semantic,
            MemoryKind.PROCEDURAL: procedural,
        }

    def remember(self, item: MemoryItem) -> None:
        """存储记忆"""
        self._backends[item.kind].store(item)

    def recall(self, query: RecallQuery) -> list[MemoryItem]:
        """召回记忆，按显著性排序"""
        items = []
        for kind in query.kinds:
            items.extend(self._backends[kind].recall(query))
        items.sort(key=lambda x: x.effective_salience(), reverse=True)
        return items[:query.limit]

    def promote(self, item: MemoryItem, to_kind: MemoryKind) -> None:
        """提升记忆层级"""
        new_item = MemoryItem(
            kind=to_kind,
            content=item.content,
            salience=item.salience,
        )
        self._backends[to_kind].store(new_item)

    def clear_working(self) -> None:
        """清空工作记忆"""
        self._backends[MemoryKind.WORKING].clear()
```

#### 使用示例

```python
memory = MemoryService(
    working=InMemoryBackend(),
    episodic=JsonlFileBackend("session_123/episodic.jsonl"),
    semantic=PostgresBackend(connection),
    procedural=YamlConfigBackend("rules.yaml"),
)

# 存储当前问题到工作记忆
memory.remember(MemoryItem(
    kind=MemoryKind.WORKING,
    content={"question": "请解释 Redis 的持久化机制"},
    salience=1.0,
))

# 召回相关记忆
items = memory.recall(RecallQuery(
    kinds=[MemoryKind.EPISODIC, MemoryKind.SEMANTIC],
    filters={"topic": "redis"},
    limit=5,
))

# 轮次结束，提升重要记忆
memory.promote(current_question, MemoryKind.EPISODIC)
memory.clear_working()
```

---

### 4. 上下文组装与压缩 (`harness/context/`)

管理 LLM 上下文窗口，通过分段组装和多级压缩保持高效利用。

#### 七段位组装

```
┌─────────────────────────────────────────────────────────────┐
│                    Context Window                            │
├─────────────────────────────────────────────────────────────┤
│  [0] System Prompt         (pinned, stable)     ████████    │
│  [1] Global Rules          (pinned, stable)     ███         │
│  [2] Tool Definitions      (unpinned, stable)   ████        │
│  [3] Profile / Skills      (unpinned, unstable) █████       │
│  [4] Compact Summary       (unpinned, unstable) ██          │
│  [5] Recent Messages       (unpinned, unstable) ████████    │
│  [6] Tool Outputs          (unpinned, unstable) ███         │
└─────────────────────────────────────────────────────────────┘
```

| 段位 | 内容 | 缓存策略 |
|-----|------|---------|
| 0 | System Prompt | 固定，可缓存前缀 |
| 1 | 全局规则 | 固定，可缓存前缀 |
| 2 | 工具定义 | 稳定，按需更新 |
| 3 | 用户画像/技能 | 会话级，按需更新 |
| 4 | 压缩摘要 | 压缩后更新 |
| 5 | 最近消息 | 滚动窗口 |
| 6 | 工具输出 | 每轮清理 |

#### 五层压缩管道

当 token 使用超过 `budget * compaction_ratio` 时触发：

```
┌─────────────────────────────────────────────────────────────┐
│                   Compaction Pipeline                        │
├─────────────────────────────────────────────────────────────┤
│  Layer 1: Tool Output Summarization                          │
│           将工具输出压缩为摘要                                │
│                         ▼                                    │
│  Layer 2: Rolling Window Truncation                          │
│           截断早期消息，保留最近 N 轮                          │
│                         ▼                                    │
│  Layer 3: Keyword Extraction                                 │
│           从截断内容提取关键词                                │
│                         ▼                                    │
│  Layer 4: Message Merging                                    │
│           合并相邻同角色消息                                  │
│                         ▼                                    │
│  Layer 5: Full Context Rewrite                               │
│           LLM 重写整个上下文（最后手段）                       │
└─────────────────────────────────────────────────────────────┘
```

#### 使用示例

```python
from agent_hub.harness.context import ContextAssembler, CompactionPipeline

assembler = ContextAssembler(token_budget=24000)
pipeline = CompactionPipeline(model_client)

# 组装上下文
context = assembler.assemble(
    system_prompt="你是面试官...",
    rules=global_rules,
    tools=tool_specs,
    profile=candidate_profile,
    summary=compact_summary,
    messages=recent_messages,
    tool_outputs=current_outputs,
)

# 检查是否需要压缩
if assembler.estimate_tokens(context) > token_budget * 0.85:
    context = pipeline.compact(context)
```

---

### 5. 工具系统 (`harness/tools/`)

统一的工具注册和调用机制。

#### 工具规约

```python
@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict = field(default_factory=dict)
    # 参数格式: {"param": {"type": "str", "required": True, "description": "..."}}

@dataclass
class Tool:
    spec: ToolSpec
    func: Callable[..., Any]

    def __call__(self, **kwargs) -> Any:
        # 参数校验
        for name, meta in self.spec.parameters.items():
            if meta.get("required") and name not in kwargs:
                raise ValueError(f"Missing required parameter: {name}")
        return self.func(**kwargs)
```

#### ToolRegistry

```python
class ToolRegistry:
    def register(
        self,
        name: str,
        description: str,
        parameters: dict | None = None,
    ) -> Callable[[Callable], Callable]:
        """装饰器注册"""
        def decorator(func: Callable) -> Callable:
            spec = ToolSpec(name, description, parameters or {})
            self._tools[name] = Tool(spec, func)
            return func
        return decorator

    def call(self, name: str, **kwargs) -> Any:
        """调用工具"""
        return self._tools[name](**kwargs)

    def specs(self) -> list[ToolSpec]:
        """获取所有工具规约（用于 LLM）"""
        return [t.spec for t in self._tools.values()]
```

#### 使用示例

```python
registry = ToolRegistry()

@registry.register(
    name="search_questions",
    description="搜索面试题库",
    parameters={
        "role": {"type": "str", "required": True, "description": "岗位"},
        "topic": {"type": "str", "required": False, "description": "主题"},
        "difficulty": {"type": "int", "required": False, "description": "难度 1-5"},
    }
)
def search_questions(role: str, topic: str = None, difficulty: int = None):
    # 实现搜索逻辑
    ...

# 调用
result = registry.call("search_questions", role="backend", topic="redis")
```

---

### 6. 会话管理 (`harness/session/`)

工厂模式管理会话生命周期，确保每个会话有隔离的执行环境。

#### SessionFactory

```python
class SessionFactory:
    """会话工厂"""

    def __init__(
        self,
        model_client,
        planner_factory: Callable[..., Planner],
        verifier_factory: Callable[..., Verifier],
        memory_factory: Callable[..., MemoryService],
        subagent_factories: dict[str, Callable[..., SubAgent]],
        bounds: Bounds | None = None,
    ):
        ...

    def build(self, session_id: str, **kwargs) -> HarnessLoop:
        """创建隔离的会话实例"""
        # 1. 创建隔离的记忆空间
        memory = self._memory_factory(session_id=session_id, **kwargs)

        # 2. 创建子 Agent 实例
        subagents = {
            name: factory(self._model, memory, **kwargs)
            for name, factory in self._subagent_factories.items()
        }

        # 3. 创建规划器和校验器
        planner = self._planner_factory(memory, subagents, **kwargs)
        verifier = self._verifier_factory(**kwargs)

        # 4. 组装执行器
        executor = self._build_executor(subagents, memory)

        # 5. 返回状态机
        return HarnessLoop(
            planner=planner,
            verifier=verifier,
            executor=executor,
            bounds=self._bounds,
        )
```

#### SessionStore

```python
class SessionStore:
    """进程内会话存储"""

    def __init__(self, factory: SessionFactory):
        self._factory = factory
        self._sessions: dict[str, HarnessLoop] = {}

    def create(self, session_id: str, **kwargs) -> HarnessLoop:
        loop = self._factory.build(session_id, **kwargs)
        self._sessions[session_id] = loop
        return loop

    def get(self, session_id: str) -> HarnessLoop | None:
        return self._sessions.get(session_id)

    def delete(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)

    def list_active(self) -> list[str]:
        return [
            sid for sid, loop in self._sessions.items()
            if loop.state.phase != Phase.HALT
        ]
```

---

## 与现有 Agent 整合

### 模式 A：Harness 作为内部实现

适用于需要状态机能力的复杂 Agent。

```python
from agent_hub.core.contracts import Agent, AgentManifest, ExecutionContext
from agent_hub.harness.session import SessionStore

class MockInterviewAgent:
    manifest = AgentManifest(
        agent_id="mock-interview",
        version="2.0.0",
        tags=("interview", "harness")
    )

    def __init__(self, session_store: SessionStore):
        self._sessions = session_store

    def invoke(self, action: str, payload: dict, context: ExecutionContext):
        if action == "create_session":
            loop = self._sessions.create(
                session_id=payload["session_id"],
                role=payload["role"],
                difficulty=payload["difficulty"],
            )
            return {"session_id": payload["session_id"], "status": "created"}

        elif action == "step":
            loop = self._sessions.get(payload["session_id"])
            if loop is None:
                raise InvalidInvocationError("Session not found")

            result = loop.step(context={"message": payload["message"]})
            return {
                "response": result,
                "phase": loop.state.phase.name,
                "turn": loop.state.turn,
            }

        elif action == "end_session":
            self._sessions.delete(payload["session_id"])
            return {"status": "ended"}
```

### 模式 B：HarnessAgent 基类

提供通用的会话管理逻辑，子类只需实现业务逻辑。

```python
from agent_hub.harness import HarnessAgent

class MyHarnessAgent(HarnessAgent):
    manifest = AgentManifest(...)

    def create_planner(self, memory, subagents, **kwargs) -> Planner:
        return MyPlanner(memory, subagents)

    def create_verifier(self, **kwargs) -> Verifier:
        return MyVerifier()

    def create_subagents(self) -> dict[str, type[SubAgent]]:
        return {
            "examiner": ExaminerAgent,
            "grader": GraderAgent,
        }
```

### 模式 C：渐进采用

现有 Agent 可以只使用部分 Harness 能力：

```python
# 只使用工具注册表
from agent_hub.harness.tools import ToolRegistry

class MyAgent:
    def __init__(self):
        self.tools = ToolRegistry()
        self._register_tools()

    def _register_tools(self):
        @self.tools.register("my_tool", "描述")
        def my_tool(param: str):
            ...

# 只使用记忆系统
from agent_hub.harness.memory import MemoryService, InMemoryBackend

class MyAgent:
    def __init__(self):
        self.memory = MemoryService(
            working=InMemoryBackend(),
            episodic=InMemoryBackend(),
            semantic=InMemoryBackend(),
            procedural=InMemoryBackend(),
        )
```

---

## 配置

### 环境变量

```bash
# Harness 边界配置
HARNESS_MAX_TURNS=30
HARNESS_MAX_REPLANS=3
HARNESS_MAX_TOOL_CALLS_PER_TURN=5
HARNESS_TOKEN_BUDGET=24000
HARNESS_COMPACTION_RATIO=0.85

# 记忆持久化
HARNESS_MEMORY_DIR=/var/lib/agent-hub/memory
HARNESS_EPISODIC_BACKEND=jsonl  # jsonl | postgres
HARNESS_SEMANTIC_BACKEND=postgres
```

### YAML 配置

```yaml
# harness.yaml
bounds:
  max_turns: 30
  max_replans: 3
  max_tool_calls_per_turn: 5
  token_budget: 24000
  compaction_ratio: 0.85

memory:
  working:
    backend: inmemory
  episodic:
    backend: jsonl
    path: "{session_dir}/episodic.jsonl"
  semantic:
    backend: postgres
    table: harness_semantic_memory
  procedural:
    backend: yaml
    path: "rules.yaml"

compaction:
  layers:
    - tool_output_summarization
    - rolling_window
    - keyword_extraction
    - message_merging
    # - full_context_rewrite  # 可选
```

---

## 可观测性

### 状态转移日志

```python
def on_transition(old: Phase, new: Phase, state: LoopState):
    logger.info(
        "phase_transition",
        old=old.name,
        new=new.name,
        turn=state.turn,
        replan_count=state.replan_count,
        errors=state.errors[-3:] if state.errors else [],
    )
```

### Transcript 事件记录

```python
@dataclass
class TranscriptEvent:
    timestamp: float
    event_type: str  # phase_transition | tool_call | subagent_execute | error
    data: dict

class Transcript:
    def __init__(self, path: Path):
        self._path = path

    def record(self, event: TranscriptEvent):
        with open(self._path, "a") as f:
            f.write(json.dumps(asdict(event)) + "\n")

    def replay(self) -> Iterator[TranscriptEvent]:
        with open(self._path) as f:
            for line in f:
                yield TranscriptEvent(**json.loads(line))
```

### 指标

| 指标 | 描述 |
|-----|------|
| `harness_turns_total` | 总轮次数 |
| `harness_replans_total` | 总重规划次数 |
| `harness_phase_duration_seconds` | 各阶段耗时 |
| `harness_tool_calls_total` | 工具调用次数 |
| `harness_token_usage` | Token 使用量 |
| `harness_compaction_triggered` | 压缩触发次数 |

---

## 测试策略

### 单元测试

```python
# 测试状态转移
def test_loop_transitions():
    loop = HarnessLoop(
        planner=MockPlanner(),
        verifier=AlwaysPassVerifier(),
        executor=lambda p, s: {"result": "ok"},
    )

    result = loop.step({})

    assert loop.state.phase == Phase.IDLE
    assert loop.state.turn == 1
    assert result == {"result": "ok"}

# 测试重规划
def test_replan_on_verify_failure():
    loop = HarnessLoop(
        planner=MockPlanner(),
        verifier=FailNTimesVerifier(n=2),  # 前两次失败
        executor=lambda p, s: {"result": "ok"},
    )

    result = loop.step({})

    assert loop.state.replan_count == 0  # 成功后重置
    assert len(loop.state.errors) == 2
```

### 集成测试

```python
# 测试完整会话流程
def test_interview_session():
    store = SessionStore(interview_factory)

    # 创建会话
    loop = store.create("session-1", role="backend", difficulty=3)

    # 执行多轮
    for message in ["你好", "Redis 持久化有哪些方式？", "结束"]:
        result = loop.step({"message": message})
        assert result is not None

    # 验证状态
    assert loop.state.turn >= 3
    assert loop.state.phase in (Phase.IDLE, Phase.HALT)
```

---

## 迁移指南

### 从简单 Agent 迁移到 Harness

1. **评估需求**：是否需要多轮对话、状态管理、上下文压缩？
2. **选择模式**：完整 Harness 还是部分采用？
3. **实现 Planner**：定义规划逻辑
4. **实现 Verifier**：定义校验规则
5. **拆分 SubAgent**：识别可隔离的子任务
6. **配置记忆**：选择合适的持久化后端
7. **集成测试**：验证状态转移和边界条件

### 检查清单

- [ ] 定义 `Bounds` 边界约束
- [ ] 实现 `Planner` 规划器
- [ ] 实现 `Verifier` 校验器
- [ ] 定义 `SubAgent` 及其 `allowed_tools`
- [ ] 配置 `MemoryService` 各层后端
- [ ] 设置 `ContextAssembler` 和 `CompactionPipeline`
- [ ] 注册所有工具到 `ToolRegistry`
- [ ] 配置 `SessionFactory`
- [ ] 添加可观测性钩子
- [ ] 编写单元测试和集成测试

---

## 参考

- [InterviewForge 项目](../references/interviewforge/)：Harness 模式的参考实现
- [系统架构](./system-architecture.md)：Agent Hub 整体架构
- [新增 Agent 指南](./adding-agents.md)：如何添加新的 Agent
