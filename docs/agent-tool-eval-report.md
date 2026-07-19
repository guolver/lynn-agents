# Agent 工具选择评测报告

> 生成命令：`python scripts/eval_agent_tools.py --trials 3 --temperature 0.7`，model=deepseek-chat。
> 评测走线上同一路径（同一系统提示词、同一工具清单、同一 API 与温度），
> 只评首个工具决策、不执行工具，零副作用可复现。

## 总览

- 用例数：30（每用例 3 trials，共 90 样本）
- 工具选择正确率：**92.2%**
- no_tool 误调用率：**0.0%**
- 参数正确率（工具选对的样本中）：**100.0%**

## 分类别正确率

| 类别 | 正确率 |
|---|---|
| edge | 77.8% |
| get_job_detail | 100.0% |
| get_my_profile | 100.0% |
| no_tool | 100.0% |
| parse_resume | 100.0% |
| run_matches | 58.3% |
| search_jobs | 100.0% |
| update_preferences | 100.0% |

多 trial 不稳定用例：match-03, edge-01, edge-03

## 失败样本

| 用例 | 期望 | 实际 | 问题 |
|---|---|---|---|
| match-01 | run_matches | get_my_profile | 工具选择错误 |
| match-01 | run_matches | get_my_profile | 工具选择错误 |
| match-01 | run_matches | get_my_profile | 工具选择错误 |
| match-03 | run_matches | get_my_profile | 工具选择错误 |
| match-03 | run_matches | get_my_profile | 工具选择错误 |
| edge-01 | no_tool/search_jobs | get_my_profile | 工具选择错误 |
| edge-03 | no_tool/run_matches | get_my_profile | 工具选择错误 |

## 提示词迭代记录（评测驱动改进）

| 版本 | 系统提示词变更 | 工具选择正确率 |
|---|---|---|
| v0 | 原始提示词 | 68.9% |
| v1 | + "候选人 ID 已提供时直接调 run_matches / update_preferences，不先查档案"、"问有没有某类职位先用 search_jobs 查真实数据" | 86.7% |
| v2 | + "'根据我的简历推荐'同样直接调 run_matches（匹配内部会读档案）；get_my_profile 只用于查看资料" | 92.2% |

v0 的主要失败模式：模型在候选人已绑定时仍先调 `get_my_profile` "确认档案"再行动
（`run_matches` 类正确率仅 8.3%），以及部分职位询问凭印象直接回答不查数据。
两条提示词规则分别修复后，`update_preferences`/`search_jobs` 达到 100%。

**为什么停在 92.2%**：剩余失败集中在 match-01/match-03（"根据我的简历/技能"表述仍触发
先查档案），且该行为在完整多轮循环中并非有害——模型查完档案后通常仍会调 run_matches，
只是多一轮往返；首轮决策指标对此从严计错。继续针对个别用例措辞调提示词有过拟合评测集
的风险，故保留该失败作为已知项，后续靠扩充用例多样性再评估。

## 已知局限

- 只评首个工具决策，不评多轮工具链与最终回答质量；
- 线上温度非 0，结果存在抖动，建议以 3 trials 的均值为准；
- 用例为人工构造的单轮/短历史场景，真实多轮长对话的表现需线上反馈补充。
