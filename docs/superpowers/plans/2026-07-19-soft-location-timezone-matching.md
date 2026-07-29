# 国家与时区软匹配 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 国家和时区不再淘汰职位，但继续通过 `location_timezone` 分项影响匹配排序。

**Architecture:** 保持现有“pgvector 召回 → 硬过滤 → 多维评分”结构，仅收窄纯领域函数 `hard_filter()` 的职责。国家和时区兼容性继续由 `score_match()` 计算，因此 API 与数据结构无需变化；同步更新规则版本以区分新旧匹配记录。

**Tech Stack:** Python 3.10+、unittest、FastAPI 业务领域层

## Global Constraints

- 不修改 pgvector 查询接口、召回窗口大小或职位数据模型。
- 不删除候选人或职位上的国家、时区字段。
- 不完全忽略国家与时区对排序的影响。
- 现有 API 响应结构保持不变。
- 其余候选人授权、职位状态、风险审核、排除公司、工作模式、语言、薪资、工时和已发送职位硬过滤保持不变。

---

## File Structure

- Modify: `agent_hub/agents/global_part_time/domain.py` — 删除国家/时区硬过滤并更新规则版本；保留现有软评分实现。
- Modify: `tests/test_domain.py` — 覆盖硬过滤行为和地区/时区排序差异。
- Modify: `tests/test_service.py` — 覆盖完整匹配用例，证明不匹配地区/时区的职位仍产生 match。

### Task 1: 将国家和时区改为软评分条件

**Files:**
- Modify: `agent_hub/agents/global_part_time/domain.py:18,165-207`
- Test: `tests/test_domain.py`
- Test: `tests/test_service.py`

**Interfaces:**
- Consumes: `hard_filter(candidate: dict[str, Any], job: dict[str, Any], already_sent: bool = False) -> list[str]`
- Consumes: `score_match(candidate: dict[str, Any], job: dict[str, Any], ...) -> tuple[float, dict[str, Any], list[str]]`
- Produces: `hard_filter()` 不再返回 `country_mismatch` 或 `timezone_mismatch`；`score_breakdown["location_timezone"]` 继续反映两项兼容性；新 match 使用 `RULE_VERSION = "2026-07-19.1"`。

- [ ] **Step 1: 修改领域测试以定义软过滤和排序行为**

将 `tests/test_domain.py` 中 `test_hard_filters_are_deterministic` 改为：

```python
def test_country_and_timezone_mismatches_are_soft_constraints(self):
    self.job["countries_allowed"] = ["US"]
    self.job["compensation_max"] = 10
    self.job["timezone_requirements"] = ["UTC-05:00"]

    failures = hard_filter(self.candidate, self.job)

    self.assertNotIn("country_mismatch", failures)
    self.assertNotIn("timezone_mismatch", failures)
    self.assertIn("compensation_below_minimum", failures)
```

并在同一测试类增加排序测试：

```python
def test_location_and_timezone_matches_score_higher_without_filtering(self):
    mismatched = dict(
        self.job,
        countries_allowed=["US"],
        timezone_requirements=["UTC-05:00"],
    )

    matching_score, matching_breakdown, _ = score_match(self.candidate, self.job)
    mismatched_score, mismatched_breakdown, _ = score_match(self.candidate, mismatched)

    self.assertEqual(hard_filter(self.candidate, mismatched), [])
    self.assertGreater(
        matching_breakdown["location_timezone"],
        mismatched_breakdown["location_timezone"],
    )
    self.assertGreater(matching_score, mismatched_score)
```

- [ ] **Step 2: 增加服务层回归测试**

在 `tests/test_service.py` 的 `ServiceWorkflowTest` 增加：

```python
def test_run_matches_keeps_country_and_timezone_mismatches(self):
    self.service.review_source(self.source["id"], True, "operator")
    mismatched_job = dict(
        self.job,
        countries_allowed=["US"],
        timezone_requirements=["UTC-05:00"],
    )
    self.service.sync_source(self.source["id"], [mismatched_job], "worker")
    candidate = self.candidate()

    result = self.service.run_matches(candidate["id"], "scheduler")

    self.assertEqual(len(result["matches"]), 1)
    self.assertEqual(result["matches"][0]["rule_version"], "2026-07-19.1")
    self.assertNotIn(
        "country_mismatch",
        [reason for item in result["filtered"] for reason in item["reasons"]],
    )
    self.assertNotIn(
        "timezone_mismatch",
        [reason for item in result["filtered"] for reason in item["reasons"]],
    )
```

- [ ] **Step 3: 运行新增测试并确认按预期失败**

Run:

```bash
source .venv/bin/activate
python -m unittest \
  tests.test_domain.DomainRulesTest.test_country_and_timezone_mismatches_are_soft_constraints \
  tests.test_domain.DomainRulesTest.test_location_and_timezone_matches_score_higher_without_filtering \
  tests.test_service.ServiceWorkflowTest.test_run_matches_keeps_country_and_timezone_mismatches -v
```

Expected: 三个测试因 `hard_filter()` 仍返回 `country_mismatch` / `timezone_mismatch` 而失败；服务层测试得到零个 match。

- [ ] **Step 4: 实现最小领域规则修改**

在 `agent_hub/agents/global_part_time/domain.py` 把规则版本更新为：

```python
RULE_VERSION = "2026-07-19.1"
```

从 `hard_filter()` 删除以下逻辑：

```python
countries = set(job.get("countries_allowed") or [])
if countries and "GLOBAL" not in countries and candidate.get("country") not in countries:
    failures.append("country_mismatch")
if not timezone_matches(candidate.get("timezone"), job.get("timezone_requirements") or []):
    failures.append("timezone_mismatch")
```

不要修改 `score_match()` 中 `location_timezone` 的计算。

- [ ] **Step 5: 运行定向测试并确认通过**

Run:

```bash
source .venv/bin/activate
python -m unittest \
  tests.test_domain.DomainRulesTest.test_country_and_timezone_mismatches_are_soft_constraints \
  tests.test_domain.DomainRulesTest.test_location_and_timezone_matches_score_higher_without_filtering \
  tests.test_service.ServiceWorkflowTest.test_run_matches_keeps_country_and_timezone_mismatches -v
```

Expected: `Ran 3 tests`，`OK`。

- [ ] **Step 6: 运行完整后端测试和代码检查**

Run:

```bash
source .venv/bin/activate
python -m unittest discover -s tests -v
ruff check src/ tests/
ruff format --check src/ tests/
```

Expected: unittest 零失败、零错误；两个 ruff 命令退出码均为 0。

- [ ] **Step 7: 检查差异并提交实现**

Run:

```bash
git diff --check
git diff -- agent_hub/agents/global_part_time/domain.py tests/test_domain.py tests/test_service.py
git status --short
```

确认只包含本任务文件后执行：

```bash
git add agent_hub/agents/global_part_time/domain.py tests/test_domain.py tests/test_service.py
git commit --only agent_hub/agents/global_part_time/domain.py tests/test_domain.py tests/test_service.py \
  -m "fix: make location and timezone matching soft"
```
