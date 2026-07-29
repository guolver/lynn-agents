"""简历解析模块：PDF 文本提取 + DeepSeek LLM 结构化解析。

职责单一：接收 PDF 字节 → 提取文本 → 调 LLM → 返回对齐 CandidateCreate schema 的字典。
"""

from __future__ import annotations

import json
import logging
import os

import httpx
from pypdf import PdfReader
from openai import OpenAI

logger = logging.getLogger(__name__)

# DeepSeek API 超时配置（秒）
# - connect: 建立连接的超时
# - read: 等待响应的超时（LLM 生成需要较长时间）
# - write: 发送请求的超时
# - pool: 连接池获取连接的超时
DEEPSEEK_TIMEOUT = httpx.Timeout(
    connect=10.0,
    read=90.0,
    write=10.0,
    pool=10.0,
)

SYSTEM_PROMPT = """\
你是一个简历解析器。请从以下简历文本中提取结构化信息，返回 JSON 对象，字段如下：

- country: ISO 3166-1 alpha-2 国家代码（如 "CN", "US", "SG"）
- timezone: IANA 时区名称或 UTC 偏移（如 "Asia/Shanghai", "UTC+08:00"）
- email: 邮箱地址，如果找不到则为 null
- languages: 语言列表，每项 {code: 语言代码, level: "native"|"fluent"|"working"|"basic"}
- skills: 技能列表，每项 {name: 技能名称, level: 1-5 的整数}
- desired_roles: 期望职位列表（字符串数组）
- minimum_hourly_rate: 最低时薪，格式 {amount: 数字, currency: 货币代码}，如果找不到则为 null
- availability_hours_per_week: 每周可用工时（整数），如果找不到默认 20
- allowed_work_modes: 工作模式列表，可选值 "remote", "hybrid", "onsite"
- resume_summary: 100~200 字的职业概要，概括工作方向、核心项目与职责、擅长领域；使用简历原语言；若简历中没有任何工作或项目经历内容则为 null

只返回 JSON 对象，不要任何额外说明。如果某个字段无法从简历中推断，使用合理的默认值。
"""


def extract_text_from_pdf(pdf_bytes: bytes) -> str:
    """用 pypdf 从 PDF 字节中提取纯文本。"""
    import io

    reader = PdfReader(io.BytesIO(pdf_bytes))
    pages = [page.extract_text() or "" for page in reader.pages]
    return "\n".join(pages).strip()


def parse_resume(text: str) -> dict:
    """调 DeepSeek API（OpenAI 兼容）解析简历文本，返回结构化字段字典。"""
    api_key = os.getenv("DEEPSEEK_API_KEY", "")
    base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    model = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

    if not api_key:
        raise ValueError("DEEPSEEK_API_KEY environment variable is not set")

    client = OpenAI(api_key=api_key, base_url=base_url, timeout=DEEPSEEK_TIMEOUT)

    logger.info("Calling DeepSeek API for resume parsing (timeout: 90s read)")
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": text},
        ],
        response_format={"type": "json_object"},
        temperature=0.1,
    )

    content = response.choices[0].message.content or "{}"
    parsed = json.loads(content)

    # 确保关键字段存在并有合理默认值
    parsed.setdefault("country", "CN")
    parsed.setdefault("timezone", "UTC+08:00")
    parsed.setdefault("languages", [])
    parsed.setdefault("skills", [])
    parsed.setdefault("desired_roles", [])
    parsed.setdefault("availability_hours_per_week", 20)
    parsed.setdefault("allowed_work_modes", ["remote"])
    parsed.setdefault("resume_summary", None)

    return parsed
