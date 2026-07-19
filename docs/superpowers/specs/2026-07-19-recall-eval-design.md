# 设计：召回能力评测（关键词 baseline vs pgvector 向量召回）

日期：2026-07-19
状态：已确认

## 目标

用可复现的离线评测证明"向量召回提升非关键词场景下的召回能力"，产出可写进简历/面试可讲的 Recall@K 对比数字。评测走与线上完全相同的路径（真实 embedding API + 真实 pgvector 检索）。

## 决策记录

| 决策点 | 结论 |
|---|---|
| 评测数据 | 合成改写测试集（脚本自带 JSON fixtures），~30 职位 + ~10 候选人 + qrels |
| 执行方式 | 方案 A：直连 `DATABASE_URL` 的真实 PG，灌入 `eval-` 前缀数据，跑完默认清理 |
| 关键词 baseline | 候选人 skills + desired_roles 词条对职位 title/description/skills 大小写无关子串匹配，按命中数排序 |
| 指标 | Recall@5/10/20 + MRR，按「全体 / 改写子集」分组 |
| 降级策略 | 无 —— 无 API key 或 PG 不可达直接报错退出，评测不做静默降级 |

## 文件

- `scripts/eval_dataset.json` — 评测数据集：
  - `jobs[]`：id（`eval-job-*`）、title_original、description_original、skills、categories、countries_allowed=["GLOBAL"]、languages、compensation_max 等入库必需字段
  - `candidates[]`：id 标识（`eval-cand-*`）、skills、desired_roles、country/timezone/languages/weekly_hours_available
  - `qrels`：{candidate_key: [job_id, ...]} 人工标注的相关对
  - `paraphrase_candidates`：改写子集的 candidate_key 列表（技能词与相关职位零/低重叠的样本）
  - 内容设计：约半数候选人为改写对（如候选人"分布式爬虫/K8s"↔职位"Data Collection Platform / container orchestration"），中英混合；其余为直接匹配对；职位含设计/市场类干扰项
- `scripts/eval_recall.py` — 主脚本（argparse：`--k 5,10,20`、`--keep`、`--report <path>`）
- `tests/test_eval_recall.py` — 纯函数单测

## 流程

```
读 eval_dataset.json
  → 灌入 PG：专用 source（eval-source，直接 repo.put 置 approved）+ jobs + candidates
  → 批量 get_embeddings(build_job_text) → repo.update_job_embeddings（任一职位向量失败 → 报错退出）
  → 对每个候选人：
      keyword_rank = keyword_baseline(candidate, all_jobs)   # 纯函数
      vector_rank  = repo.search_jobs_by_embedding(embed(build_candidate_text(c)), K_max)
  → 计算 Recall@K / MRR（纯函数），按全体与改写子集分组
  → 输出终端对比表；--report 时写 markdown
  → 清理：删除全部 eval- 前缀 job/candidate/source（--keep 跳过）
```

## 纯函数接口（可单测）

```python
def keyword_rank(candidate: dict, jobs: list[dict]) -> list[str]:
    """按关键词命中数降序返回 job_id 列表（命中数 0 的不召回）。"""

def recall_at_k(ranked: list[str], relevant: set[str], k: int) -> float: ...
def mrr(ranked: list[str], relevant: set[str]) -> float: ...
```

## 错误处理

- `SILICONFLOW_API_KEY` 缺失 / embedding 返回 None / PG 连接失败 → 打印明确原因，非零退出。
- 清理阶段包在 finally 中：即使评测中途失败也执行（--keep 除外）。

## 测试

- `tests/test_eval_recall.py`：keyword_rank 命中排序与零命中排除、recall_at_k 边界（k>len、空 relevant）、mrr（首位命中=1、无命中=0）。不依赖 PG/网络。
- 端到端：真实运行一次脚本作为验收（需要 compose PG + 有效 key）。

## 不做的事（YAGNI）

- 不做 LLM 辅助标注、不做在线 A/B、不做 nDCG（小数据集上无增益）。
- 不把评测集扩到百级——先出第一版数字，不够再扩。
