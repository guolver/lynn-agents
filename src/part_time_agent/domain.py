"""兼容旧领域规则导入；新代码请使用 agent_hub 包。"""

from agent_hub.agents.global_part_time.domain import (
    RULE_VERSION,
    SCORE_WEIGHTS,
    RiskResult,
    assess_risk,
    canonicalize_url,
    dedup_key,
    hard_filter,
    score_match,
    timezone_matches,
    utcnow,
)

__all__ = [
    "RULE_VERSION",
    "SCORE_WEIGHTS",
    "RiskResult",
    "assess_risk",
    "canonicalize_url",
    "dedup_key",
    "hard_filter",
    "score_match",
    "timezone_matches",
    "utcnow",
]

