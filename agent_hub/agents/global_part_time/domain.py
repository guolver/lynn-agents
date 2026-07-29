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

from agent_hub.skill_graph.types import ExpansionEvidence, ExpansionResult


RULE_VERSION = "2026-07-19.2"
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
# 内容质量信号：描述是聚合站转载存根（截断样板文），不是真实 JD。
STUB_DESCRIPTION_MARKERS = {
    "see this and similar jobs on linkedin",
    "upgrade to premium to see salary",
}
# skills 超过该数量视为标签堆砌（正常职位 3~10 个），会污染技能匹配。
MAX_SKILLS_BEFORE_STUFFING = 12


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
    description = str(job.get("description_original", "")).casefold()
    for marker in sorted(STUB_DESCRIPTION_MARKERS):
        if marker in description:
            signals.append(f"stub_description:{marker[:30]}")
            score += 0.25
            break
    if len(job.get("skills") or []) > MAX_SKILLS_BEFORE_STUFFING:
        signals.append("tag_stuffing")
        score += 0.25
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


def _score_from_dimensions(
    candidate: dict[str, Any],
    job: dict[str, Any],
    skill: float,
    skill_inf: bool,
    skill_reasons: list[str],
    embed_fn: Callable[[str], list[float] | None] | None = None,
    semantic_similarity: float | None = None,
) -> tuple[float, dict[str, Any], list[str]]:
    """信息完备度加权打分：无信息分项剔除，剩余分项归一化后乘完备度折扣。

    ``skill``/``skill_inf``/``skill_reasons`` are precomputed by the caller so this
    aggregation is shared between the legacy set-expansion skill scorer and the
    skill-graph evidence scorer.
    """
    semantic, semantic_inf = _semantic_score(
        candidate, job, embed_fn, precomputed=semantic_similarity
    )
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
    compensation = min(float(maximum) / max(float(minimum), 1), 1.0) if compensation_inf else 0.0
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

    positive_reasons = list(skill_reasons)
    if semantic_inf and semantic >= 0.7:
        positive_reasons.append("简历经历与岗位职责语义高度相似")
    elif semantic_inf and semantic >= 0.35:
        positive_reasons.append("简历经历与岗位职责具有相关性")
    if preference >= 1:
        positive_reasons.append("职位类别符合你的目标方向")
    if language_inf and language >= 1:
        positive_reasons.append("候选人语言能力满足职位语言要求")
    if compensation >= 1:
        positive_reasons.append("薪资达到最低期望")
    if availability_inf and availability >= 0.7:
        positive_reasons.append("每周可用工时满足职位需求")
    has_country_requirement = bool(countries) and "GLOBAL" not in countries
    has_timezone_requirement = bool(job.get("timezone_requirements"))
    if has_country_requirement and location >= 1 and has_timezone_requirement and timezone >= 1:
        positive_reasons.append("工作地区与时区均满足职位要求")
    elif has_country_requirement and location >= 1:
        positive_reasons.append("工作地区满足职位要求")
    elif has_timezone_requirement and timezone >= 1:
        positive_reasons.append("工作时区满足职位要求")
    if freshness_quality >= 0.75:
        positive_reasons.append("岗位信息完整度和可信度较高")

    reasons = positive_reasons[:5]
    if completeness < LOW_COMPLETENESS_THRESHOLD:
        reasons.append("职位信息不完整，评分仅供参考")
    return total, breakdown, reasons or ["该职位通过了你的全部硬性条件"]


def score_match(
    candidate: dict[str, Any],
    job: dict[str, Any],
    expand_fn: Callable[[list[str]], set[str]] | None = None,
    embed_fn: Callable[[str], list[float] | None] | None = None,
    semantic_similarity: float | None = None,
) -> tuple[float, dict[str, Any], list[str]]:
    """历史三元组签名：直接/集合扩展技能打分 + 信息完备度加权。"""
    skill, skill_inf, direct_skills, indirect_skills = _skill_score(candidate, job, expand_fn)
    skill_reasons = []
    if direct_skills:
        skill_reasons.append(f"技能{', '.join(direct_skills)}与职位要求直接匹配")
    if indirect_skills:
        skill_reasons.append(f"候选人技能通过类别扩展与职位要求的{', '.join(indirect_skills)}相关")
    return _score_from_dimensions(
        candidate, job, skill, skill_inf, skill_reasons, embed_fn, semantic_similarity
    )


def _legacy_score_match(
    candidate: dict[str, Any],
    job: dict[str, Any],
    expand_fn: Callable[[list[str]], set[str]] | None = None,
    embed_fn: Callable[[str], list[float] | None] | None = None,
    semantic_similarity: float | None = None,
) -> tuple[float, dict[str, Any], list[str]]:
    """技能维度回退路径：无 skill-graph evidence 时，用集合扩展打分。"""
    skill, skill_inf, direct_skills, indirect_skills = _skill_score(candidate, job, expand_fn)
    skill_reasons = []
    if direct_skills:
        skill_reasons.append(f"技能{', '.join(direct_skills)}与职位要求直接匹配")
    if indirect_skills:
        skill_reasons.append(f"候选人技能通过类别扩展与职位要求的{', '.join(indirect_skills)}相关")
    if not direct_skills and not indirect_skills and skill >= 0.5:
        skill_reasons.append("技能与职位要求高度匹配")
    return _score_from_dimensions(
        candidate, job, skill, skill_inf, skill_reasons, embed_fn, semantic_similarity
    )


ExpandEvidenceFn = Callable[[list[str]], ExpansionResult]


def _best_path(paths: list[ExpansionEvidence]) -> ExpansionEvidence | None:
    if not paths:
        return None
    return min(paths, key=lambda item: (-item.weight, item.depth, item.nodes, item.relations))


def _canonical_zero_paths(expansion: ExpansionResult) -> list[ExpansionEvidence]:
    return [item for item in expansion.evidence if item.depth == 0]


def _graph_skill_score(
    candidate: dict[str, Any],
    job: dict[str, Any],
    expand_evidence_fn: ExpandEvidenceFn,
) -> tuple[float, list[str], dict[str, Any]]:
    owned_raw = [
        item["name"] if isinstance(item, dict) else item for item in candidate.get("skills") or []
    ]
    required_raw = list(job.get("skills") or [])
    candidate_expansion = expand_evidence_fn(owned_raw)
    required_expansions = {required: expand_evidence_fn([required]) for required in required_raw}
    owned_raw_by_normalized = {
        normalized: min(name for name in owned_raw if _norm(name) == normalized)
        for normalized in {_norm(name) for name in owned_raw}
    }

    owned_zero = _canonical_zero_paths(candidate_expansion)
    owned_canonical = {
        _norm(item.canonical_skill): item.canonical_skill
        for item in owned_zero
        if item.target_kind == "skill"
    }
    requirement_records: list[dict[str, Any]] = []
    reasons: list[str] = []
    scores: list[float] = []

    for required in required_raw:
        required_expansion = required_expansions[required]
        required_zero = _canonical_zero_paths(required_expansion)
        required_canonical = required_zero[0].canonical_skill if required_zero else required
        required_kind = required_zero[0].target_kind if required_zero else None
        path_candidates: list[tuple[ExpansionEvidence, str]] = []

        direct_raw_skill = owned_raw_by_normalized.get(_norm(required))
        if direct_raw_skill is not None and not required_zero:
            path_candidates.append(
                (
                    ExpansionEvidence(
                        input_skill=required,
                        canonical_skill=required,
                        target=required,
                        target_kind="skill",
                        relations=(),
                        nodes=(required,),
                        depth=0,
                        weight=1.0,
                    ),
                    direct_raw_skill,
                )
            )

        # Canonical equality covers both direct names and aliases normalized by the graph.
        for required_path in required_zero:
            candidate_skill = direct_raw_skill or owned_canonical.get(
                _norm(required_path.canonical_skill)
            )
            if candidate_skill is not None:
                path_candidates.append((required_path, candidate_skill))

        for path in candidate_expansion.evidence:
            candidate_skill = owned_canonical.get(_norm(path.canonical_skill))
            if candidate_skill is None or path.depth == 0:
                continue
            target_is_required = _norm(path.target) == _norm(required_canonical)
            if not target_is_required:
                continue

            # Candidate-side CHILD_OF is valid only when it terminates at the required category.
            category_match = (
                required_kind == "category"
                and path.target_kind == "category"
                and path.relations[-1] == "CHILD_OF"
                and "REQUIRES" not in path.relations
            )
            # Candidate-side concrete matching must start with symmetric RELATED_TO.
            related_match = (
                required_kind == "skill"
                and path.target_kind == "skill"
                and path.relations[0] == "RELATED_TO"
                and "REQUIRES" not in path.relations
            )
            if category_match or related_match:
                path_candidates.append((path, candidate_skill))

        for path in required_expansion.evidence:
            if path.depth == 0 or path.target_kind != "skill":
                continue
            candidate_skill = owned_canonical.get(_norm(path.target))
            if candidate_skill is None:
                continue
            # Job-side REQUIRES is directional; RELATED_TO is symmetric.
            if path.relations[0] in {"REQUIRES", "RELATED_TO"}:
                path_candidates.append((path, candidate_skill))

        best = _best_path([path for path, _ in path_candidates])
        candidate_skill = next(
            (skill for path, skill in path_candidates if path is best),
            None,
        )
        score = best.weight if best is not None else 0.0
        scores.append(score)
        requirement_records.append(
            {
                "required_skill": required,
                "candidate_skill": candidate_skill,
                "score": score,
                "path": best.to_dict() if best is not None else None,
            }
        )
        if best is not None:
            if best.depth == 0:
                reasons.append(f"技能{candidate_skill}与职位要求{required}直接匹配")
            else:
                relation_path = " → ".join(best.relations)
                reasons.append(
                    f"候选人技能{candidate_skill}通过{relation_path}与职位要求{required}匹配"
                )

    skill = sum(scores) / len(scores) if scores else 0.5
    return skill, reasons, {"requirements": requirement_records}


def score_match_with_evidence(
    candidate: dict[str, Any],
    job: dict[str, Any],
    expand_evidence_fn: ExpandEvidenceFn | None = None,
    embed_fn: Callable[[str], list[float] | None] | None = None,
    semantic_similarity: float | None = None,
) -> tuple[float, dict[str, Any], list[str], dict[str, Any]]:
    """Return the normal match result plus deterministic skill-graph evidence."""
    if expand_evidence_fn is None:
        total, breakdown, reasons = _legacy_score_match(
            candidate, job, embed_fn=embed_fn, semantic_similarity=semantic_similarity
        )
        return total, breakdown, reasons, {"requirements": []}

    skill_inf = bool(job.get("skills"))
    if skill_inf:
        skill, graph_reasons, graph = _graph_skill_score(candidate, job, expand_evidence_fn)
    else:
        skill, graph_reasons, graph = 0.0, [], {"requirements": []}
    total, breakdown, reasons = _score_from_dimensions(
        candidate, job, skill, skill_inf, graph_reasons, embed_fn, semantic_similarity
    )
    return total, breakdown, reasons, graph
