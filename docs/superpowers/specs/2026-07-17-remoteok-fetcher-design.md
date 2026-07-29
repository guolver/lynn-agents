# RemoteOK Fetcher 接入设计

**日期**: 2026-07-17
**状态**: Approved

## 目标

接入 RemoteOK 公开 API 作为第一个真实岗位来源，跑通 source 注册 → 数据拉取 → 字段转换 → sync_source 入库的完整管线。

## 约束

- Fetcher 放在 Agent 内部模块，不做平台级抽象
- 缺失字段设 null，让现有 `assess_risk` 风控规则自然扣分
- 交付范围：fetcher 模块 + 单元测试 + CLI 入口脚本

## 模块结构

```
agent_hub/agents/global_part_time/
└── fetchers/
    ├── __init__.py
    └── remoteok.py         # fetch() + map_job()

scripts/
└── sync_remoteok.py        # CLI 入口

tests/
└── test_remoteok_fetcher.py
```

## RemoteOK API

- 端点: `GET https://remoteok.com/api`
- 可选过滤: `?tag=python`
- 无需认证
- 返回 JSON 数组，第一个元素是 metadata（需跳过）
- 使用条款要求标注来源归属

## 字段映射

| RemoteOK 字段 | 系统字段 | 转换逻辑 |
|---|---|---|
| `id` | `source_job_id` | `str(id)` |
| `url` | `canonical_url` | 直接映射 |
| `position` | `title_original` | 直接映射 |
| `company` | `company_name` | 直接映射 |
| `description` | `description_original` | HTML strip tags → 纯文本 |
| `tags` | `skills` | 直接映射 |
| `tags` | `categories` | 直接映射（与 skills 相同） |
| `location` | `countries_allowed` | "Worldwide" → `["GLOBAL"]`；否则保留原文作为单元素列表 |
| `location` | `work_mode` | 固定 `"remote"`（RemoteOK 全部是远程岗位） |
| `salary_min` | `compensation_min` | 0 → None；非零值按年薪/2080 换算为时薪 |
| `salary_max` | `compensation_max` | 0 → None；非零值按年薪/2080 换算为时薪 |
| — | `compensation_currency` | 固定 `"USD"` |
| — | `compensation_period` | 固定 `"hour"`（已换算） |
| `epoch` | `published_at` | Unix timestamp → ISO 8601 |
| — | `employment_type` | 固定 `"part_time"` |
| — | `languages` | `[]` |
| — | `hours_per_week_min` | `None` |
| — | `hours_per_week_max` | `None` |
| — | `extraction_confidence` | `0.6`（标记为自动推断） |
| — | `quality_score` | `0.7` |

## 函数签名

### `fetch(tags: list[str] | None = None, limit: int = 200) -> list[dict]`

从 RemoteOK API 拉取原始 JSON。跳过第一个 metadata 元素。加 `User-Agent` 头标明来源。通过 `limit` 截断返回数量。

### `map_job(raw: dict) -> dict`

将单条 RemoteOK 原始数据转换为系统 `JobInput` 兼容格式。纯函数，无副作用。

### `strip_html(html: str) -> str`

移除 HTML 标签，保留纯文本。使用标准库 `html.parser`，不引入额外依赖。

## CLI 脚本流程

`scripts/sync_remoteok.py`：

1. 初始化 `SQLiteRepository` + `AgentService`
2. 调用 `service.create_source()` 注册 RemoteOK 来源
3. 调用 `service.review_source()` 审批来源
4. 调用 `fetch()` 拉取 RemoteOK 数据
5. 调用 `map_job()` 批量转换
6. 调用 `service.sync_source()` 入库（含风控 + 去重）
7. 打印统计：received / imported / duplicates / rejected / pending_review

支持 `--tags` 和 `--limit` 命令行参数。

## 测试计划

| 测试 | 验证内容 |
|------|----------|
| `test_map_job_complete` | 完整字段映射正确 |
| `test_map_job_salary_zero` | salary=0 转为 None |
| `test_map_job_salary_conversion` | 年薪正确换算为时薪 |
| `test_map_job_worldwide_location` | "Worldwide" → `["GLOBAL"]` |
| `test_map_job_html_strip` | HTML description → 纯文本 |
| `test_strip_html` | 各种 HTML 标签正确移除 |
| `test_fetch_skips_metadata` | 跳过 API 返回的第一个元素 |
| `test_end_to_end_sync` | mock HTTP → fetch → map → sync_source 全流程 |

## 不做的事情

- 不引入额外 HTTP 库（用标准库 `urllib`）
- 不做定时调度（未来用 Celery 接入）
- 不做 FetcherProtocol 抽象（等第二个来源时再提取）
- 不新增 HTTP API 端点
