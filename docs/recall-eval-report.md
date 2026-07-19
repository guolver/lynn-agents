# 召回能力评测报告

关键词 baseline vs pgvector 向量召回（真实 API + 真实检索）。

组别 | 召回方式 | Recall@5 | Recall@10 | Recall@20 | MRR
--- | --- | --- | --- | --- | ---
全体(8) | keyword | 0.469 | 0.469 | 0.469 | 0.500
全体(8) | vector | 1.000 | 1.000 | 1.000 | 1.000
改写子集(4) | keyword | 0.000 | 0.000 | 0.000 | 0.000
改写子集(4) | vector | 1.000 | 1.000 | 1.000 | 1.000

## 说明

- 评测集：30 个职位 / 8 个候选人（其中 4 个为同义改写样本——候选人技能表述与相关职位文本零关键词重叠，如"分布式爬虫"↔"Web Harvesting Platform"）。
- 关键词 baseline：候选人技能/期望角色整条词条对职位标题、描述、技能的大小写无关子串匹配，按命中数排序（等价于技能标签精确匹配）。
- 向量召回：SiliconFlow Qwen3-Embedding-0.6B（1024 维）+ PostgreSQL pgvector 余弦相似度检索，与线上 run_matches 同一路径。
- 复现：`DATABASE_URL=... python scripts/eval_recall.py --report docs/recall-eval-report.md`（数据自动灌入与清理）。

**结论**：在同义改写场景下，关键词召回 Recall@5 为 0.000，向量召回为 1.000；向量检索在非关键词场景带来从完全不可用到满召回的提升。全体样本上向量召回 Recall@5 1.000 vs 关键词 0.469。
