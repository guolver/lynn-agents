"""全球兼职 Agent 的纯领域规则。

本模块刻意不依赖 FastAPI、数据库或具体模型供应商。这样风险判断、硬过滤和
匹配分数在 HTTP 请求、后台任务和未来的 Agent 编排器中都能得到相同结果。
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable
from urllib.parse import urlsplit, urlunsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


RULE_VERSION = "2026-07-18.1"
SCORE_WEIGHTS = {
    "skills": 0.28,
    "semantic": 0.12,
    "language": 0.13,
    "location_timezone": 0.13,
    "compensation": 0.13,
    "availability": 0.08,
    "preference": 0.07,
    "freshness_quality": 0.06,
}

HIGH_RISK_TERMS = {
    "刷单",
    "博彩",
    "资金盘",
    "银行卡密码",
    "验证码",
    "先付款",
    "充值",
    "wire money",
    "bank password",
    "verification code",
    "pay upfront",
    "crypto deposit",
}
MEDIUM_RISK_TERMS = {
    "购买设备",
    "保证收益",
    "轻松月入",
    "无经验高薪",
    "buy equipment",
    "guaranteed income",
    "easy money",
    "unlimited earnings",
}


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _norm(value: str) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", value.casefold())


def canonicalize_url(url: str) -> str:
    parts = urlsplit(url.strip())
    host = (parts.hostname or "").lower()
    port = f":{parts.port}" if parts.port and parts.port not in (80, 443) else ""
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower() or "https", host + port, path, "", ""))


def timezone_matches(candidate_timezone: str | None, requirements: list[str]) -> bool:
    """判断 IANA 时区是否满足职位给出的 IANA 名称或 UTC 偏移要求。"""
    if not requirements or not candidate_timezone:
        return True
    if candidate_timezone in requirements:
        return True
    try:
        candidate_offset = datetime.now(ZoneInfo(candidate_timezone)).utcoffset()
    except ZoneInfoNotFoundError:
        return False
    for value in requirements:
        match = re.fullmatch(r"UTC([+-])(\d{2}):?(\d{2})", value)
        if match:
            minutes = int(match.group(2)) * 60 + int(match.group(3))
            expected = timedelta(minutes=minutes if match.group(1) == "+" else -minutes)
            if candidate_offset == expected:
                return True
    return False


def dedup_key(job: dict[str, Any]) -> str:
    """Cross-source stable identity; source IDs and tracking URLs are deliberately excluded."""
    countries = ",".join(sorted(job.get("countries_allowed") or []))
    description_fingerprint = _norm(job.get("description_original", ""))[:256]
    identity = "|".join(
        [
            _norm(job.get("company_name", "")),
            _norm(job.get("title_original", "")),
            countries,
            description_fingerprint,
        ]
    )
    return hashlib.sha256(identity.encode()).hexdigest()


@dataclass(frozen=True)
class RiskResult:
    score: float
    level: str
    signals: list[str]
    action: str


def assess_risk(job: dict[str, Any]) -> RiskResult:
    """用可审计的关键词和字段完整性规则计算风险，模型不得覆盖此结果。"""
    text = " ".join(
        str(job.get(k, "")) for k in ("title_original", "description_original", "company_name")
    ).casefold()
    signals: list[str] = []
    score = 0.0
    for term in sorted(HIGH_RISK_TERMS):
        if term.casefold() in text:
            signals.append(f"high_risk_term:{term}")
            score += 0.65
    for term in sorted(MEDIUM_RISK_TERMS):
        if term.casefold() in text:
            signals.append(f"medium_risk_term:{term}")
            score += 0.25
    for field in ("company_name", "description_original", "canonical_url"):
        if not job.get(field):
            signals.append(f"missing:{field}")
            score += 0.12
    if job.get("compensation_max") is None:
        signals.append("missing:compensation")
        score += 0.08
    score = min(round(score, 4), 1.0)
    if score >= 0.60:
        return RiskResult(score, "high", signals, "reject")
    if score >= 0.25:
        return RiskResult(score, "medium", signals, "review")
    return RiskResult(score, "low", signals, "accept")


def hard_filter(
    candidate: dict[str, Any], job: dict[str, Any], already_sent: bool = False
) -> list[str]:
    """返回所有硬过滤失败原因；空列表表示职位可进入排序阶段。"""
    failures: list[str] = []
    if candidate.get("consent_status") != "opted_in":
        failures.append("candidate_not_opted_in")
    if job.get("status") != "active":
        failures.append("job_not_active")
    if float(job.get("risk_score", 1)) >= 0.25 and job.get("review_status") != "approved":
        failures.append("risk_not_approved")
    if job.get("company_name") in set(candidate.get("excluded_companies") or []):
        failures.append("company_excluded")
    countries = set(job.get("countries_allowed") or [])
    if countries and "GLOBAL" not in countries and candidate.get("country") not in countries:
        failures.append("country_mismatch")
    if not timezone_matches(candidate.get("timezone"), job.get("timezone_requirements") or []):
        failures.append("timezone_mismatch")
    modes = set(candidate.get("allowed_work_modes") or [])
    if modes and job.get("work_mode") not in modes:
        failures.append("work_mode_mismatch")
    required_languages = set(job.get("languages") or [])
    candidate_languages = {
        item["code"] if isinstance(item, dict) else item
        for item in candidate.get("languages") or []
    }
    if required_languages and not required_languages.issubset(candidate_languages):
        failures.append("language_mismatch")
    minimum = (candidate.get("minimum_hourly_rate") or {}).get("amount")
    if minimum is not None and job.get("compensation_max") is not None:
        same_currency = job.get("compensation_currency") == (
            candidate.get("minimum_hourly_rate") or {}
        ).get("currency")
        if not same_currency:
            failures.append("compensation_currency_mismatch")
        if same_currency and float(job["compensation_max"]) < float(minimum):
            failures.append("compensation_below_minimum")
    max_hours = job.get("hours_per_week_min")
    if max_hours and candidate.get("availability_hours_per_week", 0) < max_hours:
        failures.append("insufficient_availability")
    if already_sent:
        failures.append("already_sent")
    return failures


def _availability_score(candidate: dict[str, Any], job: dict[str, Any]) -> float:
    """候选人工时可用性与职位需求的梯度匹配。"""
    avail = candidate.get("availability_hours_per_week", 0)
    job_min = job.get("hours_per_week_min")
    job_max = job.get("hours_per_week_max")

    if job_min is None and job_max is None:
        return 0.7  # 无要求 → 中性

    if job_max is None:
        job_max = int(job_min * 1.5) if job_min else 40
    if job_min is None:
        job_min = 0

    if avail >= job_max:
        return 1.0
    elif avail >= job_min:
        span = job_max - job_min
        return 1.0 if span == 0 else 0.7 + 0.3 * (avail - job_min) / span
    else:
        return max(0.3 * avail / max(job_min, 1), 0.0)


def _semantic_score(
    candidate: dict[str, Any],
    job: dict[str, Any],
    embed_fn: Callable[[str], list[float] | None] | None = None,
    precomputed: float | None = None,
) -> float:
    """通过 embedding 余弦相似度计算候选人与职位的语义匹配度。

    ``precomputed`` 为向量召回阶段带回的相似度；提供时跳过实时 embedding 调用。
    """
    if precomputed is None:
        if embed_fn is None:
            return 0.5
        from .embedding import build_candidate_text, build_job_text, cosine_similarity

        cand_emb = embed_fn(build_candidate_text(candidate))
        job_emb = embed_fn(build_job_text(job))
        if cand_emb is None or job_emb is None:
            return 0.5
        precomputed = cosine_similarity(cand_emb, job_emb)
    return max(0.0, min(1.0, (precomputed - 0.3) / 0.6))  # 线性映射 [0.3, 0.9] → [0, 1]


def _skill_score(
    candidate: dict[str, Any],
    job: dict[str, Any],
    expand_fn: Callable[[list[str]], set[str]] | None = None,
) -> tuple[float, list[str], list[str]]:
    raw_required = list(job.get("skills") or [])
    required = {_norm(x) for x in raw_required}
    if not required:
        return 0.5, [], []
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
    return min(score, 1.0), direct, indirect


def score_match(
    candidate: dict[str, Any],
    job: dict[str, Any],
    expand_fn: Callable[[list[str]], set[str]] | None = None,
    embed_fn: Callable[[str], list[float] | None] | None = None,
    semantic_similarity: float | None = None,
) -> tuple[float, dict[str, float], list[str]]:
    """按照版本化权重生成可复现总分、分项分数和面向用户的理由。"""
    skill, direct_skills, indirect_skills = _skill_score(candidate, job, expand_fn)
    semantic = _semantic_score(candidate, job, embed_fn, precomputed=semantic_similarity)
    required_langs = set(job.get("languages") or [])
    owned_langs = {
        x["code"] if isinstance(x, dict) else x for x in candidate.get("languages") or []
    }
    language = len(required_langs & owned_langs) / len(required_langs) if required_langs else 1.0
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
    compensation = (
        0.5
        if maximum is None or minimum is None
        else min(float(maximum) / max(float(minimum), 1), 1.0)
    )
    availability = _availability_score(candidate, job)
    desired = set(candidate.get("desired_roles") or [])
    categories = set(job.get("categories") or [])
    preference = 1.0 if not desired or desired & categories else 0.4
    quality = float(job.get("quality_score", 0.5))
    freshness_quality = min(max(quality, 0.0), 1.0)
    breakdown = {
        "skills": round(skill, 4),
        "semantic": round(semantic, 4),
        "language": round(language, 4),
        "location_timezone": round(location_timezone, 4),
        "compensation": round(compensation, 4),
        "availability": round(availability, 4),
        "preference": round(preference, 4),
        "freshness_quality": round(freshness_quality, 4),
    }
    total = round(sum(breakdown[k] * SCORE_WEIGHTS[k] for k in SCORE_WEIGHTS), 4)
    reasons = []
    if direct_skills:
        reasons.append(f"技能{', '.join(direct_skills)}与职位要求直接匹配")
    if indirect_skills:
        reasons.append(f"候选人技能通过类别扩展与职位要求的{', '.join(indirect_skills)}相关")
    if not direct_skills and not indirect_skills and skill >= 0.5:
        reasons.append("技能与职位要求高度匹配")
    if semantic >= 0.7:
        reasons.append("简历与职位描述语义高度相似")
    if location_timezone >= 0.7:
        reasons.append("地区与工作时区满足要求")
    if compensation >= 1:
        reasons.append("薪资达到最低期望")
    if availability >= 0.8:
        reasons.append("可用工时充分满足职位需求")
    if preference >= 1:
        reasons.append("职位类别符合你的偏好")
    return total, breakdown, reasons or ["该职位通过了你的全部硬性条件"]
