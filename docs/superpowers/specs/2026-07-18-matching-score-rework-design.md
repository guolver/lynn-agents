# 匹配打分规则重构：信息完备度加权 + 简历内容语义匹配

日期：2026-07-18
状态：已确认（方案 B + 简历内容匹配补充）
RULE_VERSION：`2026-07-18.1` → `2026-07-18.2`

## 背景与问题

当前 `score_match`（`agent_hub/agents/global_part_time/domain.py`）对"缺信息"给中性偏高分：职位不列技能 0.5、不限语言 1.0、不填工时 0.7、候选人没填偏好 1.0。信息稀疏职位可堆到约 68~75%，反超技能真实命中的职位。另有理由文案 bug（无技能要求时误报「技能与职位要求高度匹配」）、语义权重过低（0.12）、且语义文本只含技能列表——简历工作内容完全没参与匹配。

## 目标

1. 信息越少分越低（至少不占便宜），技能/内容真实命中的职位排前。
2. 理由文案与事实一致。
3. 简历工作内容与职位描述产生真实语义匹配（召回 + 精排）。

## 设计

### 1. 分项有效性（informative）

打分函数为每个分项返回 `(score, informative)`；仅 informative 分项参与总分：

| 分项 | 无信息判定（剔除） | 有信息时打分 |
|---|---|---|
| skills | 职位 `skills` 为空 | 不变；0 命中 = 0 分（删除 0.5 保底） |
| semantic | 无相似度可用（无 embedding 且无召回相似度） | 不变 |
| language | 职位 `languages` 为空 | 不变（不再给 1.0） |
| compensation | 职位无 `compensation_max` 或候选人无 `minimum_hourly_rate` | 不变 |
| availability | 职位 `hours_per_week_min`、`hours_per_week_max` 均为空 | 不变（不再给 0.7） |
| preference | 候选人 `desired_roles` 为空 | 不变（不命中仍 0.4） |
| location_timezone | 永远参与（"全球可投"是真实正面信号） | 不变 |
| freshness_quality | 永远参与 | 不变 |

### 2. 归一化 + 完备度折扣

```
base         = Σ(wₖ·sₖ, k∈informative) / Σ(wₖ, k∈informative)
completeness = Σ(wₖ, k∈informative)          # ∈ (0, 1]，权重总和为 1
factor       = COMPLETENESS_FLOOR + (1 - COMPLETENESS_FLOOR) × completeness
total        = round(base × factor, 4)
COMPLETENESS_FLOOR = 0.5                      # 模块级常量，可调
```

极端情况：所有分项都 informative → factor = 1（与直接加权求和等价）。location_timezone 与 freshness_quality 永远参与，completeness 下界约 0.17，不会除零。

### 3. 权重调整（SCORE_WEIGHTS，总和 1.0）

| 分项 | 旧 | 新 |
|---|---|---|
| skills | 0.28 | 0.32 |
| semantic | 0.12 | 0.18 |
| language | 0.13 | 0.11 |
| location_timezone | 0.13 | 0.11 |
| compensation | 0.13 | 0.11 |
| availability | 0.08 | 0.06 |
| preference | 0.07 | 0.05 |
| freshness_quality | 0.06 | 0.06 |

### 4. 理由文案

- 删除 `not direct and not indirect and skill >= 0.5 → 「技能与职位要求高度匹配」` 分支（该场景在新规则下只剩"职位没列技能"，已被剔除，不应输出技能理由）。
- `completeness < 0.7` 时在 reasons 末尾追加：「职位信息不完整，评分仅供参考」。
- 其余理由触发条件不变。

### 5. 简历内容 ↔ 职位描述语义匹配

- `resume_parser.SYSTEM_PROMPT` 增加输出字段 `resume_summary`：100~200 字职业概要（工作方向、核心项目职责、擅长领域；使用简历原语言）。同一次 LLM 调用，无新依赖。找不到相关内容时为 null。
- 候选人创建链路把 `resume_summary` 存入 candidate payload（`CandidateCreate` schema 增加可选字段，直通 payload）。
- `embedding.build_candidate_text` 在现有 Skills / Desired roles 之后追加 `Experience: {resume_summary}`（截断 1500 字符）。该文本同时服务 pgvector 召回与 semantic 精排。
- `build_job_text` 本次不改（职位向量已存库，改动需全量重算，收益低）。
- 兼容：无 `resume_summary` 的老候选人文本退化为现状，无迁移。

### 6. 数据结构与兼容

- `score_breakdown` 保留全部 8 个分项的原始分（数值，前端不破坏），新增键：
  - `completeness`: float
  - `uninformative`: list[str]（被剔除的分项名）
- match 记录携带 `rule_version = "2026-07-18.2"`，旧记录可追溯。
- 召回流程、硬过滤、HTTP API、前端均不改。改动面：`domain.py`（主要）、`resume_parser.py`（prompt+schema）、`embedding.py`（build_candidate_text）、candidate schema、相关单测。

### 7. 测试与验收

更新 `tests/` 中现有 score_match 断言（权重与总分变化），新增：

1. 排序验收：构造"信息稀疏职位"（无技能/语言/工时要求）与"技能命中职位"（列 6 项技能命中 3 项、信息齐全），后者总分必须更高。
2. informative 判定：逐分项验证剔除条件。
3. 折扣公式：completeness=1 时 factor=1；缺失 skills+semantic+language 时 total 按公式回落。
4. 理由：无技能要求的职位不得输出「技能与职位要求高度匹配」；completeness<0.7 输出「职位信息不完整，评分仅供参考」。
5. build_candidate_text：有/无 resume_summary 两种情况的输出。
6. resume_parser：mock LLM 返回含 resume_summary 的 JSON，验证字段透传。

验收以**排序正确性**为准（真实命中 > 信息稀疏），绝对百分比只作参考。

## 明确不做（YAGNI）

- 发布时间新鲜度衰减、召回相似度直接融合排序（方案 C，观察本次效果后再评估）。
- build_job_text 扩充与职位向量重算。
- 前端展示 completeness/uninformative（数据已在 breakdown 里，界面后续按需加）。
