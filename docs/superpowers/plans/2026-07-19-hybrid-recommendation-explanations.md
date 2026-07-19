# 混合推荐理由 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 每条聊天岗位推荐展示一句批量 LLM 生成的个性化总结，以及最多五条来自评分数据的确定性依据。

**Architecture:** `domain.py` 只生成可审计依据；新增 `recommendation_explainer.py` 负责一次批量 DeepSeek 请求和严格输出校验；`chat_tools.py` 在职位详情富化后附加可选总结；前端把总结和依据分层展示。LLM 失败不影响匹配、评分或排序。

**Tech Stack:** Python 3.10、OpenAI-compatible DeepSeek API、unittest/pytest、React 19、TypeScript

## Global Constraints

- LLM 不得修改匹配分数、排序、硬过滤结果或确定性依据。
- 每次匹配最多一次模型请求，只处理前五条岗位。
- 总结必须使用批次内 job ID，且不超过 120 个中文字符。
- 未配置密钥、供应商错误或非法输出必须降级为只有确定性依据。
- 旧 match 和旧聊天历史没有 `recommendation_summary` 时继续兼容。
- 不修改数据库模型、pgvector 召回或评分权重。

---

## File Structure

- Modify: `src/agent_hub/agents/global_part_time/domain.py` — 扩展多维确定性理由并更新规则版本。
- Create: `src/agent_hub/agents/global_part_time/recommendation_explainer.py` — 批量生成和校验个性化总结。
- Modify: `src/agent_hub/agents/global_part_time/chat_tools.py` — 调用解释器并附加总结。
- Modify: `frontend/components/chat-message.tsx` — 分层渲染总结和理由。
- Modify: `tests/test_domain.py` — 覆盖理由维度、上限和真实性。
- Create: `tests/test_recommendation_explainer.py` — 覆盖批量调用和降级。
- Modify: `tests/test_chat_tools.py` — 覆盖总结集成与失败降级。

### Task 1: 扩展确定性多维理由

**Files:**
- Modify: `src/agent_hub/agents/global_part_time/domain.py`
- Test: `tests/test_domain.py`

**Interfaces:**
- Consumes: `score_match(candidate, job, ..., semantic_similarity=None)`
- Produces: 最多五条正向 `reasons`，可另附一条低完备度提示；`RULE_VERSION = "2026-07-19.2"`。

- [ ] **Step 1: 添加失败测试**

在 `DomainRulesTest` 中增加语义、语言、工时和质量理由断言；在 `CompletenessWeightingTests` 增加正向理由上限断言：

```python
def test_reasons_cover_multiple_informative_dimensions(self):
    _, _, reasons = score_match(self.candidate, self.job, semantic_similarity=0.9)
    combined = "|".join(reasons)
    self.assertIn("技能", combined)
    self.assertIn("语义高度相似", combined)
    self.assertIn("语言要求", combined)
    self.assertTrue("薪资" in combined or "可用工时" in combined)

def test_positive_reasons_are_capped_at_five(self):
    _, _, reasons = score_match(self.candidate, self.rich_job, semantic_similarity=0.9)
    positive = [reason for reason in reasons if "评分仅供参考" not in reason]
    self.assertLessEqual(len(positive), 5)
```

- [ ] **Step 2: 运行测试确认失败**

Run:

```bash
.venv/bin/python -m unittest \
  tests.test_domain.DomainRulesTest.test_reasons_cover_multiple_informative_dimensions \
  tests.test_domain.CompletenessWeightingTests.test_positive_reasons_are_capped_at_five -v
```

Expected: 缺少语言等理由或正向理由超过五条时 FAIL。

- [ ] **Step 3: 实现理由选择**

把 `RULE_VERSION` 更新为 `2026-07-19.2`。在 `score_match()` 中按以下优先级构建 `positive_reasons`：直接技能、关联技能、语义、目标方向、语言、薪资、工时、地区/时区、职位质量。语义分 `>= 0.7` 使用“简历经历与岗位职责语义高度相似”，`>= 0.35` 使用“简历经历与岗位职责具有相关性”；语言只在全部满足时生成；地区和时区只描述实际满足项；质量分 `>= 0.75` 才生成理由。

最终返回逻辑使用：

```python
reasons = positive_reasons[:5]
if completeness < LOW_COMPLETENESS_THRESHOLD:
    reasons.append("职位信息不完整，评分仅供参考")
return total, breakdown, reasons or ["该职位通过了你的全部硬性条件"]
```

- [ ] **Step 4: 运行领域测试**

Run: `.venv/bin/python -m unittest tests.test_domain -v`

Expected: 全部 PASS。

### Task 2: 实现批量 LLM 推荐总结

**Files:**
- Create: `src/agent_hub/agents/global_part_time/recommendation_explainer.py`
- Create: `tests/test_recommendation_explainer.py`

**Interfaces:**
- Produces: `generate_recommendation_summaries(candidate: dict, matches: list[dict], jobs_by_id: dict[str, dict]) -> dict[str, str]`
- Environment: `DEEPSEEK_API_KEY`、`DEEPSEEK_BASE_URL`、`DEEPSEEK_MODEL`

- [ ] **Step 1: 添加失败测试**

测试使用 monkeypatch 替换模块内 `OpenAI`，模拟 `response.choices[0].message.content`。覆盖：一次请求映射两个 job ID；只处理前五条；未知 ID、非字符串和超过 120 字的值被丢弃；无密钥和 API 异常返回 `{}`。

核心成功断言：

```python
summaries = generate_recommendation_summaries(candidate, matches, jobs_by_id)
assert summaries == {"j1": "你的 React 经验与该岗位的前端职责高度契合。"}
assert fake_client.chat.completions.create.call_count == 1
```

- [ ] **Step 2: 运行测试确认模块缺失**

Run: `.venv/bin/python -m pytest tests/test_recommendation_explainer.py -v`

Expected: import error 或函数缺失。

- [ ] **Step 3: 实现解释器**

模块定义：

```python
MAX_SUMMARY_JOBS = 5
MAX_SUMMARY_LENGTH = 120

def generate_recommendation_summaries(
    candidate: dict[str, Any],
    matches: list[dict[str, Any]],
    jobs_by_id: dict[str, dict[str, Any]],
) -> dict[str, str]:
    ...
```

函数在无密钥或无 match 时立即返回 `{}`；请求使用 `response_format={"type": "json_object"}`、`temperature=0.2` 和 15 秒超时。输入职位职责截断至 1200 字。解析后仅保留允许 job ID、非空字符串且长度不超过 120 的值。所有异常记录 warning 并返回 `{}`。

- [ ] **Step 4: 运行解释器测试**

Run: `.venv/bin/python -m pytest tests/test_recommendation_explainer.py -v`

Expected: 全部 PASS。

### Task 3: 接入聊天工具并安全降级

**Files:**
- Modify: `src/agent_hub/agents/global_part_time/chat_tools.py`
- Modify: `tests/test_chat_tools.py`

**Interfaces:**
- Consumes: `generate_recommendation_summaries(candidate, matches, jobs_by_id)`
- Produces: 合法 summary 写入对应 match 的可选 `recommendation_summary` 字段。

- [ ] **Step 1: 添加失败测试**

配置 `service.run_matches`、`service.repo.list("job")` 和 `service.get_candidate()`，monkeypatch `chat_tools.generate_recommendation_summaries` 返回 `{"j1": "个性化总结"}`，断言：

```python
assert result["matches"][0]["recommendation_summary"] == "个性化总结"
```

另一个测试让解释器返回 `{}`，断言 match 正常返回且没有 `recommendation_summary`。

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_chat_tools.py -v`

Expected: 新增测试因总结未附加而 FAIL。

- [ ] **Step 3: 实现集成**

在 `run_matches` 分支完成职位详情富化后：

```python
candidate = service.get_candidate(candidate_id)
summaries = generate_recommendation_summaries(
    candidate,
    result.get("matches", []),
    jobs_by_id,
)
for match in result.get("matches", []):
    summary = summaries.get(match.get("job_id"))
    if summary:
        match["recommendation_summary"] = summary
```

解释器自身负责降级，聊天工具不改变原始 matches。

- [ ] **Step 4: 运行聊天工具测试**

Run: `.venv/bin/python -m pytest tests/test_chat_tools.py -v`

Expected: 全部 PASS。

### Task 4: 前端分层展示总结与依据

**Files:**
- Modify: `frontend/components/chat-message.tsx`

**Interfaces:**
- Consumes: `recommendation_summary?: string`、`reasons?: string[]`
- Produces: 有总结时显示灯泡总结；确定性理由传入 `MatchCard` 标签区。

- [ ] **Step 1: 修改类型和渲染**

在 match 类型增加：

```typescript
recommendation_summary?: string;
```

把卡片循环中的外层理由改为：

```tsx
{m.recommendation_summary && (
  <div className="chat-match-reason">
    <span className="chat-match-reason-icon">💡</span>
    {m.recommendation_summary}
  </div>
)}
```

并把 `MatchCard` 的 `reasons={[]}` 改为：

```tsx
reasons={m.reasons ?? []}
```

- [ ] **Step 2: 运行前端检查**

Run:

```bash
cd frontend
pnpm lint
pnpm build
```

Expected: 两个命令退出码均为 0；旧历史数据不要求该可选字段。

### Task 5: 完整验证与提交

**Files:**
- Verify all files above.

**Interfaces:**
- Consumes: Tasks 1–4 的最终实现。
- Produces: 已验证、可部署的混合推荐理由功能。

- [ ] **Step 1: 运行后端验证**

Run:

```bash
.venv/bin/python -m unittest \
  tests.test_domain -v
.venv/bin/python -m pytest \
  tests/test_recommendation_explainer.py tests/test_chat_tools.py -v
rg --files tests -g 'test_*.py' | rg -v 'tests/test_skill_graph.py' | xargs .venv/bin/python -m unittest
.venv/bin/ruff check src/ tests/
.venv/bin/ruff format --check \
  src/agent_hub/agents/global_part_time/domain.py \
  src/agent_hub/agents/global_part_time/recommendation_explainer.py \
  src/agent_hub/agents/global_part_time/chat_tools.py \
  tests/test_domain.py tests/test_recommendation_explainer.py tests/test_chat_tools.py
```

Expected: 定向测试和除已知 Neo4j 文件外的后端测试通过；Ruff 退出码为 0。

- [ ] **Step 2: 检查并提交**

Run: `git diff --check && git status --short`

只提交本计划列出的源代码和测试：

```bash
git add \
  src/agent_hub/agents/global_part_time/domain.py \
  src/agent_hub/agents/global_part_time/recommendation_explainer.py \
  src/agent_hub/agents/global_part_time/chat_tools.py \
  tests/test_domain.py tests/test_recommendation_explainer.py tests/test_chat_tools.py \
  frontend/components/chat-message.tsx
git commit --only \
  src/agent_hub/agents/global_part_time/domain.py \
  src/agent_hub/agents/global_part_time/recommendation_explainer.py \
  src/agent_hub/agents/global_part_time/chat_tools.py \
  tests/test_domain.py tests/test_recommendation_explainer.py tests/test_chat_tools.py \
  frontend/components/chat-message.tsx \
  -m "feat: add hybrid recommendation explanations"
```
