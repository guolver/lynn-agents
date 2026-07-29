# 匹配打分重构（信息完备度加权 + 简历语义）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让信息稀疏的职位不再靠中性分反超真实匹配的职位，并让简历工作内容参与语义匹配。

**Architecture:** 纯后端。`domain.py` 的各分项打分函数返回 `(score, informative)`，`score_match` 只对 informative 分项加权归一并乘以完备度折扣；`resume_parser` 多提取 `resume_summary` 存入候选人 payload；`build_candidate_text` 追加该概要，使 pgvector 召回和 semantic 精排都基于简历内容。召回、硬过滤、API、前端不动。

**Tech Stack:** Python 3.10 / unittest / ruff。测试命令 `python -m unittest tests.test_domain -v`（在仓库根目录、激活 `.venv` 后运行）。

**Spec:** `docs/superpowers/specs/2026-07-18-matching-score-rework-design.md`

**注意：** 工作区可能有其他会话的未提交改动。提交时只 `git add` 本任务列出的文件，禁止 `git add -A`/`git add .`。

---

### Task 1: domain.py 完备度加权重构（TDD）

**Files:**
- Modify: `agent_hub/agents/global_part_time/domain.py`
- Test: `tests/test_domain.py`

- [ ] **Step 1: 在 `tests/test_domain.py` 末尾追加新测试类**

```python
class CompletenessWeightingTests(unittest.TestCase):
    """信息完备度加权：缺信息分项剔除 + 归一化 + 折扣（spec 2026-07-18）。"""

    def setUp(self):
        self.candidate = {
            "skills": [{"name": "python"}, {"name": "react"}, {"name": "typescript"}],
            "languages": [{"code": "en"}],
            "country": "CN",
            "timezone": "Asia/Shanghai",
            "minimum_hourly_rate": {"amount": 20, "currency": "USD"},
            "availability_hours_per_week": 20,
            "desired_roles": ["backend"],
        }
        self.rich_job = {
            "title_original": "Backend Engineer",
            "skills": ["python", "react", "typescript", "go", "rust", "kafka"],
            "languages": ["en"],
            "countries_allowed": ["GLOBAL"],
            "timezone_requirements": [],
            "compensation_max": 40,
            "compensation_currency": "USD",
            "hours_per_week_min": 10,
            "hours_per_week_max": 20,
            "categories": ["backend"],
            "quality_score": 0.5,
        }
        self.sparse_job = {
            "title_original": "Head of Marketing",
            "countries_allowed": ["GLOBAL"],
            "compensation_max": 110,
            "compensation_currency": "USD",
            "quality_score": 0.5,
        }

    def test_sparse_job_ranks_below_matching_job(self):
        rich_score, _, _ = score_match(self.candidate, self.rich_job)
        sparse_score, _, _ = score_match(self.candidate, self.sparse_job)
        self.assertGreater(rich_score, sparse_score)

    def test_uninformative_components_listed(self):
        _, breakdown, _ = score_match(self.candidate, self.sparse_job)
        for key in ("skills", "semantic", "language", "availability"):
            self.assertIn(key, breakdown["uninformative"])
        self.assertNotIn("location_timezone", breakdown["uninformative"])
        self.assertNotIn("preference", breakdown["uninformative"])

    def test_full_information_no_discount(self):
        total, breakdown, _ = score_match(self.candidate, self.rich_job, semantic_similarity=0.9)
        self.assertEqual(breakdown["uninformative"], [])
        self.assertEqual(breakdown["completeness"], 1.0)
        expected = round(
            0.32 * 0.5 + 0.18 * 1.0 + 0.11 * 1.0 + 0.11 * 1.0 + 0.11 * 1.0
            + 0.06 * 1.0 + 0.05 * 1.0 + 0.06 * 0.5,
            4,
        )
        self.assertAlmostEqual(total, expected, places=4)

    def test_discount_formula_on_sparse_job(self):
        total, breakdown, _ = score_match(self.candidate, self.sparse_job)
        # informative: location_timezone 0.11(=1.0) + compensation 0.11(=1.0)
        # + preference 0.05(=0.4) + freshness_quality 0.06(=0.5) → active=0.33
        base = (0.11 * 1.0 + 0.11 * 1.0 + 0.05 * 0.4 + 0.06 * 0.5) / 0.33
        factor = 0.5 + 0.5 * 0.33
        self.assertAlmostEqual(breakdown["completeness"], 0.33, places=4)
        self.assertAlmostEqual(total, round(base * factor, 4), places=3)

    def test_no_skill_requirement_never_claims_skill_match(self):
        _, _, reasons = score_match(self.candidate, self.sparse_job)
        self.assertFalse(any("技能" in r for r in reasons))

    def test_low_completeness_adds_disclaimer(self):
        _, _, reasons = score_match(self.candidate, self.sparse_job)
        self.assertIn("职位信息不完整，评分仅供参考", reasons)

    def test_high_completeness_has_no_disclaimer(self):
        _, _, reasons = score_match(self.candidate, self.rich_job)
        self.assertNotIn("职位信息不完整，评分仅供参考", reasons)

    def test_zero_skill_overlap_scores_zero_not_half(self):
        job = {**self.rich_job, "skills": ["golang", "rust"]}
        _, breakdown, _ = score_match(self.candidate, job)
        self.assertEqual(breakdown["skills"], 0.0)
        self.assertNotIn("skills", breakdown["uninformative"])
```

- [ ] **Step 2: 运行新测试，确认失败**

Run: `python -m unittest tests.test_domain.CompletenessWeightingTests -v`
Expected: FAIL/ERROR（`breakdown["uninformative"]` 不存在等）。

- [ ] **Step 3: 修改 `domain.py` 常量**

把文件头部的 `RULE_VERSION` 与 `SCORE_WEIGHTS` 替换为：

```python
RULE_VERSION = "2026-07-18.2"
SCORE_WEIGHTS = {
    "skills": 0.32,
    "semantic": 0.18,
    "language": 0.11,
    "location_timezone": 0.11,
    "compensation": 0.11,
    "availability": 0.06,
    "preference": 0.05,
    "freshness_quality": 0.06,
}
# 完备度折扣：total = base × (FLOOR + (1-FLOOR) × completeness)
COMPLETENESS_FLOOR = 0.5
# completeness 低于该阈值时在理由中追加"信息不完整"提示
LOW_COMPLETENESS_THRESHOLD = 0.7
```

- [ ] **Step 4: 改造三个分项函数为返回 informative 标记**

`_availability_score` 整体替换为：

```python
def _availability_score(candidate: dict[str, Any], job: dict[str, Any]) -> tuple[float, bool]:
    """候选人工时可用性与职位需求的梯度匹配；职位未填工时要求时视为无信息。"""
    avail = candidate.get("availability_hours_per_week", 0)
    job_min = job.get("hours_per_week_min")
    job_max = job.get("hours_per_week_max")

    if job_min is None and job_max is None:
        return 0.0, False

    if job_max is None:
        job_max = int(job_min * 1.5) if job_min else 40
    if job_min is None:
        job_min = 0

    if avail >= job_max:
        return 1.0, True
    elif avail >= job_min:
        span = job_max - job_min
        return (1.0 if span == 0 else 0.7 + 0.3 * (avail - job_min) / span), True
    else:
        return max(0.3 * avail / max(job_min, 1), 0.0), True
```

`_semantic_score` 整体替换为（相似度映射不变，仅无信息时返回 False）：

```python
def _semantic_score(
    candidate: dict[str, Any],
    job: dict[str, Any],
    embed_fn: Callable[[str], list[float] | None] | None = None,
    precomputed: float | None = None,
) -> tuple[float, bool]:
    """通过 embedding 余弦相似度计算语义匹配度；无相似度可用时视为无信息。

    ``precomputed`` 为向量召回阶段带回的相似度；提供时跳过实时 embedding 调用。
    """
    if precomputed is None:
        if embed_fn is None:
            return 0.0, False
        from .embedding import build_candidate_text, build_job_text, cosine_similarity

        cand_emb = embed_fn(build_candidate_text(candidate))
        job_emb = embed_fn(build_job_text(job))
        if cand_emb is None or job_emb is None:
            return 0.0, False
        precomputed = cosine_similarity(cand_emb, job_emb)
    return max(0.0, min(1.0, (precomputed - 0.3) / 0.6)), True  # 线性映射 [0.3, 0.9] → [0, 1]
```

`_skill_score` 整体替换为（返回值增加 informative；0 命中不再有 0.5 保底）：

```python
def _skill_score(
    candidate: dict[str, Any],
    job: dict[str, Any],
    expand_fn: Callable[[list[str]], set[str]] | None = None,
) -> tuple[float, bool, list[str], list[str]]:
    raw_required = list(job.get("skills") or [])
    required = {_norm(x) for x in raw_required}
    if not required:
        return 0.0, False, [], []
    raw_owned = [x["name"] if isinstance(x, dict) else x for x in candidate.get("skills") or []]
    owned = {_norm(x) for x in raw_owned}
    direct_set = required & owned
    indirect_set: set[str] = set()
    if expand_fn:
        expanded_owned = owned | {_norm(x) for x in expand_fn(raw_owned)}
        for raw_skill in raw_required:
            normalized = _norm(raw_skill)
            if normalized in direct_set:
                continue
            expanded_required = {normalized} | {_norm(x) for x in expand_fn([raw_skill])}
            if expanded_owned & expanded_required:
                indirect_set.add(normalized)
    direct = sorted(direct_set)
    indirect = sorted(indirect_set)
    score = (len(direct) + len(indirect) * 0.6) / len(required)
    return min(score, 1.0), True, direct, indirect
```

- [ ] **Step 5: 重写 `score_match`**

整体替换为：

```python
def score_match(
    candidate: dict[str, Any],
    job: dict[str, Any],
    expand_fn: Callable[[list[str]], set[str]] | None = None,
    embed_fn: Callable[[str], list[float] | None] | None = None,
    semantic_similarity: float | None = None,
) -> tuple[float, dict[str, Any], list[str]]:
    """信息完备度加权打分：无信息分项剔除，剩余分项归一化后乘完备度折扣。"""
    skill, skill_inf, direct_skills, indirect_skills = _skill_score(candidate, job, expand_fn)
    semantic, semantic_inf = _semantic_score(candidate, job, embed_fn, precomputed=semantic_similarity)
    required_langs = set(job.get("languages") or [])
    owned_langs = {
        x["code"] if isinstance(x, dict) else x for x in candidate.get("languages") or []
    }
    language_inf = bool(required_langs)
    language = len(required_langs & owned_langs) / len(required_langs) if required_langs else 0.0
    countries = set(job.get("countries_allowed") or [])
    location = (
        1.0
        if not countries or "GLOBAL" in countries or candidate.get("country") in countries
        else 0.0
    )
    timezone = float(
        timezone_matches(candidate.get("timezone"), job.get("timezone_requirements") or [])
    )
    location_timezone = 0.7 * location + 0.3 * timezone
    minimum = (candidate.get("minimum_hourly_rate") or {}).get("amount")
    maximum = job.get("compensation_max")
    compensation_inf = maximum is not None and minimum is not None
    compensation = (
        min(float(maximum) / max(float(minimum), 1), 1.0) if compensation_inf else 0.0
    )
    availability, availability_inf = _availability_score(candidate, job)
    desired = set(candidate.get("desired_roles") or [])
    categories = set(job.get("categories") or [])
    preference_inf = bool(desired)
    preference = (1.0 if desired & categories else 0.4) if desired else 0.0
    quality = float(job.get("quality_score", 0.5))
    freshness_quality = min(max(quality, 0.0), 1.0)

    informative = {
        "skills": skill_inf,
        "semantic": semantic_inf,
        "language": language_inf,
        "location_timezone": True,
        "compensation": compensation_inf,
        "availability": availability_inf,
        "preference": preference_inf,
        "freshness_quality": True,
    }
    breakdown: dict[str, Any] = {
        "skills": round(skill, 4),
        "semantic": round(semantic, 4),
        "language": round(language, 4),
        "location_timezone": round(location_timezone, 4),
        "compensation": round(compensation, 4),
        "availability": round(availability, 4),
        "preference": round(preference, 4),
        "freshness_quality": round(freshness_quality, 4),
    }
    active_weight = sum(SCORE_WEIGHTS[k] for k, v in informative.items() if v)
    base = sum(breakdown[k] * SCORE_WEIGHTS[k] for k, v in informative.items() if v) / active_weight
    completeness = round(active_weight, 4)
    factor = COMPLETENESS_FLOOR + (1 - COMPLETENESS_FLOOR) * active_weight
    total = round(base * factor, 4)
    breakdown["completeness"] = completeness
    breakdown["uninformative"] = sorted(k for k, v in informative.items() if not v)

    reasons = []
    if direct_skills:
        reasons.append(f"技能{', '.join(direct_skills)}与职位要求直接匹配")
    if indirect_skills:
        reasons.append(f"候选人技能通过类别扩展与职位要求的{', '.join(indirect_skills)}相关")
    if semantic_inf and semantic >= 0.7:
        reasons.append("简历与职位描述语义高度相似")
    if location_timezone >= 0.7:
        reasons.append("地区与工作时区满足要求")
    if compensation >= 1:
        reasons.append("薪资达到最低期望")
    if availability >= 0.8:
        reasons.append("可用工时充分满足职位需求")
    if preference >= 1:
        reasons.append("职位类别符合你的偏好")
    if completeness < LOW_COMPLETENESS_THRESHOLD:
        reasons.append("职位信息不完整，评分仅供参考")
    return total, breakdown, reasons or ["该职位通过了你的全部硬性条件"]
```

要点：删除了旧代码的 `if not direct_skills and not indirect_skills and skill >= 0.5` 误导分支；`location_timezone` 和 `freshness_quality` 永远 informative，`active_weight` 下界 0.17，无除零风险。

- [ ] **Step 6: 运行新测试**

Run: `python -m unittest tests.test_domain.CompletenessWeightingTests -v`
Expected: 全部 PASS。

- [ ] **Step 7: 更新 `tests/test_domain.py` 中被新规则破坏的旧断言**

Run: `python -m unittest tests.test_domain -v` 找出失败用例，按以下规则逐一修正（不许放宽成"约等于就行"，要按新公式重算）：

- `assertEqual(breakdown["semantic"], 0.5)`（无 embed_fn 的中性断言，约第 57、191 行）→ 改为：

```python
        self.assertEqual(breakdown["semantic"], 0.0)
        self.assertIn("semantic", breakdown["uninformative"])
```

- 断言具体 total 的用例：按新公式重算期望值。公式：`total = base × (0.5 + 0.5 × active_weight)`，其中 `base = Σ(wₖ·sₖ, informative) / active_weight`。无 embed_fn 且未传 semantic_similarity 时 semantic 被剔除（active_weight 少 0.18）。
- 涉及"技能与职位要求高度匹配"文案的断言：该文案已删除，改断言 `direct_skills` 对应文案或删除该断言。
- 测试里如出现职位无 `skills` 字段却断言 `breakdown["skills"] == 0.5` 的：改为 `0.0` + `assertIn("skills", breakdown["uninformative"])`。

Run: `python -m unittest tests.test_domain -v`
Expected: 全部 PASS。

- [ ] **Step 8: Commit**

```bash
git add agent_hub/agents/global_part_time/domain.py tests/test_domain.py
git commit -m "feat(matching): completeness-weighted scoring, drop neutral-score padding

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_012fhZLk4jQRXeDcuCkx5H58" -- agent_hub/agents/global_part_time/domain.py tests/test_domain.py
```

---

### Task 2: 全量测试波及修复

**Files:**
- Modify（按需）: `tests/test_service.py`、`tests/test_celery_tasks.py`、`tests/test_api.py`、其他因分数变化断言失败的测试文件。禁止改 `src/`（如发现 `src/` 真有 bug，停下报告 BLOCKED）。

- [ ] **Step 1: 跑全量测试**

Run: `python -m unittest discover -s tests -v 2>&1 | tail -30`

- [ ] **Step 2: 修复因新打分公式失败的断言**

修正原则与 Task 1 Step 7 相同：按公式重算期望值；断言排序/存在性的测试优先保持语义不变。`rule_version` 断言改为 `"2026-07-18.2"`。

- [ ] **Step 3: 全量通过 + lint**

Run: `python -m unittest discover -s tests -v 2>&1 | tail -5`
Expected: OK。
Run: `ruff check src/ tests/ && ruff format --check src/ tests/`
Expected: 通过（如 format 有 diff，运行 `ruff format src/ tests/` 后复跑测试）。

- [ ] **Step 4: Commit**

```bash
git add tests/
git commit -m "test: update assertions for completeness-weighted scoring

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_012fhZLk4jQRXeDcuCkx5H58" -- tests/
```

（注意：仅当 `git status` 显示 tests/ 下只有你改的文件时才可用 `git add tests/`，否则逐个列出文件。）

---

### Task 3: resume_summary 提取（TDD）

**Files:**
- Modify: `agent_hub/agents/global_part_time/resume_parser.py`
- Modify: `agent_hub/agents/global_part_time/http_api.py`（CandidateCreate）
- Create: `tests/test_resume_parser.py`

- [ ] **Step 1: 写失败测试 `tests/test_resume_parser.py`**

```python
"""resume_parser 的 resume_summary 提取测试（LLM 调用全部 mock）。"""

from __future__ import annotations

import json
import os
import unittest
from unittest import mock

from agent_hub.agents.global_part_time.resume_parser import parse_resume


def _fake_response(content: str):
    message = mock.Mock()
    message.content = content
    choice = mock.Mock()
    choice.message = message
    response = mock.Mock()
    response.choices = [choice]
    return response


class ResumeSummaryTests(unittest.TestCase):
    def _parse_with(self, payload: dict) -> dict:
        with (
            mock.patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test-key"}),
            mock.patch(
                "agent_hub.agents.global_part_time.resume_parser.OpenAI"
            ) as openai_cls,
        ):
            client = openai_cls.return_value
            client.chat.completions.create.return_value = _fake_response(json.dumps(payload))
            return parse_resume("resume text")

    def test_resume_summary_passthrough(self):
        parsed = self._parse_with({"country": "CN", "resume_summary": "五年后端开发，主导支付系统重构"})
        self.assertEqual(parsed["resume_summary"], "五年后端开发，主导支付系统重构")

    def test_resume_summary_defaults_to_none(self):
        parsed = self._parse_with({"country": "CN"})
        self.assertIsNone(parsed["resume_summary"])

    def test_prompt_mentions_resume_summary(self):
        from agent_hub.agents.global_part_time.resume_parser import SYSTEM_PROMPT

        self.assertIn("resume_summary", SYSTEM_PROMPT)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m unittest tests.test_resume_parser -v`
Expected: FAIL（`resume_summary` 键不存在 / SYSTEM_PROMPT 不含该词）。

- [ ] **Step 3: 修改 `resume_parser.py`**

SYSTEM_PROMPT 中 `- allowed_work_modes: ...` 一行之后追加：

```
- resume_summary: 100~200 字的职业概要，概括工作方向、核心项目与职责、擅长领域；使用简历原语言；若简历中没有任何工作或项目经历内容则为 null
```

`parse_resume` 末尾的 setdefault 块中追加一行：

```python
    parsed.setdefault("resume_summary", None)
```

- [ ] **Step 4: `http_api.py` 的 `CandidateCreate` 增加可选字段**

在 `excluded_companies: list[str] = Field(default_factory=list)` 之后加：

```python
    resume_summary: str | None = None
```

（worker 上传链路 `service.create_candidate(parsed, actor)` 直接展开 dict，无需改动；此字段让 HTTP 直接建候选人的路径保持同构。）

- [ ] **Step 5: 运行测试**

Run: `python -m unittest tests.test_resume_parser -v`
Expected: PASS。

- [ ] **Step 6: Commit**

```bash
git add agent_hub/agents/global_part_time/resume_parser.py agent_hub/agents/global_part_time/http_api.py tests/test_resume_parser.py
git commit -m "feat(resume): extract resume_summary for semantic matching

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_012fhZLk4jQRXeDcuCkx5H58" -- agent_hub/agents/global_part_time/resume_parser.py agent_hub/agents/global_part_time/http_api.py tests/test_resume_parser.py
```

---

### Task 4: build_candidate_text 追加简历概要（TDD）

**Files:**
- Modify: `agent_hub/agents/global_part_time/embedding.py`
- Test: `tests/test_embedding.py`

- [ ] **Step 1: 在 `tests/test_embedding.py` 末尾追加测试类**

先确认文件顶部已导入 `build_candidate_text`（若没有，在现有 embedding 导入处补上）。追加：

```python
class BuildCandidateTextTests(unittest.TestCase):
    def test_includes_resume_summary(self):
        text = build_candidate_text(
            {
                "skills": [{"name": "python"}],
                "desired_roles": ["backend"],
                "resume_summary": "五年后端开发经验，主导支付系统重构",
            }
        )
        self.assertIn("Skills: python", text)
        self.assertIn("Desired roles: backend", text)
        self.assertIn("Experience: 五年后端开发经验，主导支付系统重构", text)

    def test_without_resume_summary_unchanged(self):
        text = build_candidate_text({"skills": ["python"]})
        self.assertEqual(text, "Skills: python")

    def test_resume_summary_truncated_to_1500(self):
        text = build_candidate_text({"resume_summary": "x" * 2000})
        self.assertEqual(text, "Experience: " + "x" * 1500)

    def test_blank_resume_summary_ignored(self):
        text = build_candidate_text({"skills": ["python"], "resume_summary": "   "})
        self.assertEqual(text, "Skills: python")
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m unittest tests.test_embedding.BuildCandidateTextTests -v`
Expected: FAIL（缺少 Experience 段）。

- [ ] **Step 3: 修改 `embedding.py` 的 `build_candidate_text`**

在 `desired_roles` 段之后、`return` 之前追加：

```python
    resume_summary = (candidate.get("resume_summary") or "").strip()
    if resume_summary:
        parts.append("Experience: " + resume_summary[:1500])
```

并把函数 docstring 更新为：`"""将候选人的技能、期望角色与简历概要组合为一段用于 embedding 的文本。"""`

- [ ] **Step 4: 运行测试**

Run: `python -m unittest tests.test_embedding -v`
Expected: 全部 PASS。

- [ ] **Step 5: Commit**

```bash
git add agent_hub/agents/global_part_time/embedding.py tests/test_embedding.py
git commit -m "feat(embedding): include resume summary in candidate text

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_012fhZLk4jQRXeDcuCkx5H58" -- agent_hub/agents/global_part_time/embedding.py tests/test_embedding.py
```

---

### Task 5: 最终验证

**Files:** 无新改动（除非发现问题）。

- [ ] **Step 1: 全量测试 + lint**

```bash
python -m unittest discover -s tests -v 2>&1 | tail -5
ruff check src/ tests/
ruff format --check src/ tests/
```
Expected: 全部通过。

- [ ] **Step 2: 排序冒烟验证（真实公式演算）**

```bash
python - <<'EOF'
from agent_hub.agents.global_part_time.domain import score_match
candidate = {
    "skills": [{"name": "python"}, {"name": "react"}, {"name": "typescript"}],
    "languages": [{"code": "en"}],
    "minimum_hourly_rate": {"amount": 20, "currency": "USD"},
    "availability_hours_per_week": 20,
    "desired_roles": ["backend"],
    "country": "CN", "timezone": "Asia/Shanghai",
}
rich = {"title_original": "PM", "skills": ["python", "react", "typescript", "go", "rust", "kafka"],
        "languages": ["en"], "countries_allowed": ["GLOBAL"], "compensation_max": 40,
        "hours_per_week_min": 10, "hours_per_week_max": 20, "categories": ["backend"], "quality_score": 0.5}
sparse = {"title_original": "Head of Marketing", "countries_allowed": ["GLOBAL"],
          "compensation_max": 110, "quality_score": 0.5}
for name, job in (("命中岗", rich), ("稀疏岗", sparse)):
    total, bd, reasons = score_match(candidate, job)
    print(f"{name}: {total:.2%} completeness={bd['completeness']} reasons={reasons}")
EOF
```
Expected: 命中岗分数明显高于稀疏岗；稀疏岗 reasons 含「职位信息不完整，评分仅供参考」，且不含任何"技能"字样理由。把输出贴进报告。

- [ ] **Step 3: 最终代码审查后汇报**

按 superpowers:verification-before-completion：所有声明配证据（测试输出、冒烟输出）。
