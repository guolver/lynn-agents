# 新增兼职职位来源：Arbeitnow / Working Nomads / We Work Remotely

**日期**: 2026-07-19
**状态**: Approved

## 目标

在现有 4 个来源（RemoteOK、Remotive、Jobicy、Himalayas）基础上，新增 3 个免登录、免 API Key 的公开职位数据源，扩大职位覆盖面。完全复用现有 fetcher 模式（`fetch()` + `map_job()` 纯函数 + `REGISTRY` 域名注册），不改动 service/repository/agent 层。

## 约束

- 只接入无需登录、无需申请密钥即可访问的公开接口，符合 [兼职 Agent 设计文档](../../global-part-time-agent.md) §6 的来源授权要求（禁止绕过登录/验证码/访问控制）。
- 不引入新的第三方依赖；RSS 解析用标准库 `xml.etree.ElementTree`。
- 缺失字段设 `None`/`[]`，交给下游 `assess_risk`/匹配逻辑处理，不在 fetcher 层做臆测。
- 每个来源独立成模块，互不依赖；出错时相互隔离（一个来源失败不影响其他来源同步）。

## 模块结构

```
agent_hub/agents/global_part_time/fetchers/
├── arbeitnow.py          # fetch() + map_job()
├── workingnomads.py      # fetch() + map_job()
├── weworkremotely.py     # fetch() + map_job()（RSS/XML，非 JSON）
└── __init__.py           # REGISTRY 新增 3 个域名映射

tests/
├── test_arbeitnow_fetcher.py
├── test_workingnomads_fetcher.py
└── test_weworkremotely_fetcher.py
```

## 来源 1：Arbeitnow

- 端点：`GET https://www.arbeitnow.com/api/job-board-api?page=N`，无需认证，Laravel 分页（`meta.current_page` / `links.next`）。
- 实测：单页最多 100 条，混合远程与本地职位（抽样 100 条中仅 7 条 `remote: true`）；`remote` 查询参数**不生效**（服务端未按此过滤），必须客户端过滤。

### 字段映射

| Arbeitnow 字段 | 系统字段 | 转换逻辑 |
|---|---|---|
| `slug` | `source_job_id` | 直接映射 |
| `url` | `canonical_url` | 直接映射 |
| `title` | `title_original` | 直接映射 |
| `company_name` | `company_name` | 直接映射 |
| `description` | `description_original` | `sanitize_html` |
| `tags` | `skills` / `categories` | 直接映射（数组） |
| `location` | `countries_allowed` | `normalize_countries([location])`；空值 → `["GLOBAL"]` |
| `created_at`（epoch 秒） | `published_at` | Unix timestamp → ISO 8601 |
| — | `employment_type` | 固定 `"part_time"`（与其他来源一致） |
| — | `work_mode` | 固定 `"remote"`（因为已过滤 `remote != true` 的条目） |
| — | `compensation_min/max` | `None`（接口无薪资字段） |
| — | `quality_score` / `extraction_confidence` | `0.7` / `0.6` |

### `fetch(limit: int = 200, max_pages: int = 10) -> list[dict]`

逐页请求 `?page=N`，对每页结果过滤 `remote == True` 的条目后累加，直到达到 `limit` 或翻页数超过 `max_pages`（防止无限翻页）或某页返回空 `data`。

## 来源 2：Working Nomads

- 端点：`GET https://www.workingnomads.com/api/exposed_jobs/`，无需认证，一次性返回全部职位（实测约 30–40 条），无分页参数。

### 字段映射

| Working Nomads 字段 | 系统字段 | 转换逻辑 |
|---|---|---|
| `url` | `canonical_url` | 直接映射 |
| `title` | `title_original` | 直接映射 |
| `company_name` | `company_name` | 直接映射 |
| `description` | `description_original` | `sanitize_html` |
| `tags`（逗号分隔字符串） | `skills` | `split(",")` 去空白 |
| `category_name` | `categories` | `[category_name]` |
| `location`（逗号分隔地区名，如 `"Europe, North America, APAC"`） | `countries_allowed` | 按逗号拆分后传入 `normalize_countries`（地区关键词已在 `_REGION_KEYWORDS` 中支持） |
| `pub_date`（带时区 ISO8601） | `published_at` | `datetime.fromisoformat` |
| — | `employment_type` | 固定 `"part_time"` |
| — | `work_mode` | 固定 `"remote"` |
| — | `compensation_min/max` | `None`（接口无薪资字段） |
| — | `quality_score` / `extraction_confidence` | `0.7` / `0.6` |

### `fetch(limit: int = 200) -> list[dict]`

单次 GET，`[:limit]` 截断。

## 来源 3：We Work Remotely（RSS）

- 端点：`GET https://weworkremotely.com/remote-jobs.rss`，公开 RSS，无需认证。
- **与前 6 个来源的关键差异**：响应是 XML/RSS，不是 JSON。用 `xml.etree.ElementTree` 解析 `<item>` 列表，`fetch()` 直接返回字典列表（每个 `<item>` 的子标签转为 dict），交给 `map_job()` 处理，保持与其他 fetcher 一致的 `fetch() -> list[dict]` 接口约定。
- `title` 字段固定格式为 `"公司名: 职位名"`（如 `"LawnStarter: Data Governance & Platform Manager"`），需按首个 `": "` 拆分。

### 字段映射

| WWR RSS 字段 | 系统字段 | 转换逻辑 |
|---|---|---|
| `title`（拆分后半段） | `title_original` | 按首个 `": "` split，取拆分失败时整个 title 作为 title_original，company_name 为空字符串 |
| `title`（拆分前半段） | `company_name` | 同上 |
| `guid` / `link` | `canonical_url` | 优先 `link`，缺失时用 `guid` |
| `description` | `description_original` | `sanitize_html` |
| `region` | `countries_allowed` | `normalize_countries([region])`；`"Anywhere in the World"` 命中 `_GLOBAL_KEYWORDS` → `["GLOBAL"]` |
| `category` | `categories` | `[category]`（category 为空则 `[]`） |
| `type`（`"Contract"` / `"Full-Time"` 等） | `employment_type` | 含 "contract" → `"contract"`；否则默认 `"part_time"`（与其他来源一致的兜底策略） |
| `pubDate`（RFC822 格式） | `published_at` | `email.utils.parsedate_to_datetime` → ISO 8601 |
| — | `work_mode` | 固定 `"remote"` |
| — | `compensation_min/max` | `None`（RSS 无薪资字段） |
| — | `quality_score` / `extraction_confidence` | `0.7` / `0.6` |

### `fetch(limit: int = 200) -> list[dict]`

单次 GET，解析 XML `<item>` 列表为 dict 列表（字段名对应 RSS 标签名：`title`/`region`/`category`/`type`/`description`/`pubDate`/`guid`/`link`），`[:limit]` 截断。

## `REGISTRY` 注册（`fetchers/__init__.py`）

```python
"arbeitnow.com": (arbeitnow_fetch, arbeitnow_map),
"workingnomads.com": (workingnomads_fetch, workingnomads_map),
"weworkremotely.com": (weworkremotely_fetch, weworkremotely_map),
```

## 测试计划

每个来源照抄 `test_remotive_fetcher.py` 的结构，用实测抓到的真实响应样例做 fixture：

| 测试类 | 验证内容 |
|---|---|
| `MapJobCompleteTest` | 完整字段映射正确（含公司名拆分、地区展开、薪资为 None） |
| `MapJobLocationTest` | 全球/地区关键词/空值等边界情况 |
| `FetchTest`（mock `urlopen`） | Arbeitnow：分页拉取 + `remote` 过滤 + `max_pages` 上限；Working Nomads：单次拉取 + limit 截断；WWR：RSS 解析正确性 |
| `EndToEndSyncTest` | mock 响应 → fetch → map → `service.sync_source()` 全流程，验证去重 |

## 不做的事情

- 不做定时调度（沿用现有模式，未来统一接入 Celery）
- 不新增 HTTP API 端点或 CLI 脚本（现有 4 个来源里只有 RemoteOK 有 CLI 脚本，非强制模式）
- 不做 FetcherProtocol 抽象（现有代码已有 4 个来源仍未抽象，等真正出现重复痛点再提取）
- 不接入需要 API Key 或需要绕过访问限制的来源
