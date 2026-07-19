"""岗位翻译模块：调用 DeepSeek API 将英文岗位标题和描述翻译为中文。

复用 resume_parser.py 同款 OpenAI 兼容客户端模式。翻译结果由调用方缓存到
job payload 的 title_zh / description_zh 字段，避免重复调用。
"""

from __future__ import annotations

import json
import logging
import os

from openai import OpenAI

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
你是一个专业的岗位信息翻译器。请将以下英文岗位信息翻译为中文。

要求：
1. 翻译为自然流畅的中文
2. 保留 HTML 标签结构不变（如 <p>, <ul>, <li>, <strong>, <h2> 等）
3. 专业术语和技术名词可保留英文（如 React, Python, AWS, Kubernetes 等）
4. 公司名称保留英文原文
5. 薪资数字和货币符号保持原样

请返回 JSON 对象，包含两个字段：
- title_zh: 翻译后的中文标题
- description_zh: 翻译后的中文描述（保留原始 HTML 结构）

只返回 JSON 对象，不要任何额外说明。
"""


def translate_job(title: str, description_html: str) -> dict[str, str]:
    """调 DeepSeek API 翻译岗位标题和描述，返回 {title_zh, description_zh}。"""
    api_key = os.getenv("DEEPSEEK_API_KEY", "")
    base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    model = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

    if not api_key:
        raise ValueError("DEEPSEEK_API_KEY environment variable is not set")

    client = OpenAI(api_key=api_key, base_url=base_url)

    user_content = f"标题：{title}\n\n描述：\n{description_html}"

    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        response_format={"type": "json_object"},
        temperature=0.1,
    )

    content = response.choices[0].message.content or "{}"
    parsed = json.loads(content)

    return {
        "title_zh": parsed.get("title_zh", title),
        "description_zh": parsed.get("description_zh", description_html),
    }
