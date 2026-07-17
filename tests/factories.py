"""Reusable valid payloads for repository, service, and API contract tests."""

from __future__ import annotations

from typing import Any


def source_payload() -> dict[str, Any]:
    """Return a fresh valid job-source payload."""
    return {
        "name": "Approved Partner Feed",
        "source_type": "partner_feed",
        "base_url": "https://feed.example.com/",
        "authorization_basis": "partner contract",
        "allowed_paths": ["/jobs"],
        "prohibited_actions": ["login automation"],
        "rate_limit": "60/hour",
        "retention_policy": "30 days",
    }


def job_payload() -> dict[str, Any]:
    """Return a fresh valid part-time job payload."""
    return {
        "source_job_id": "job-1",
        "canonical_url": "https://feed.example.com/jobs/1?tracking=x",
        "title_original": "Python Data Evaluation",
        "company_name": "Example Ltd.",
        "description_original": "Review AI data with documented guidelines.",
        "employment_type": "part_time",
        "work_mode": "remote",
        "countries_allowed": ["CN"],
        "timezone_requirements": ["UTC+08:00"],
        "languages": ["zh-CN", "en"],
        "skills": ["python", "data_annotation"],
        "categories": ["ai_data"],
        "hours_per_week_min": 10,
        "hours_per_week_max": 20,
        "compensation_min": 15,
        "compensation_max": 25,
        "compensation_currency": "USD",
        "compensation_period": "hour",
        "quality_score": 0.9,
    }


def candidate_payload() -> dict[str, Any]:
    """Return a fresh valid candidate payload."""
    return {
        "country": "CN",
        "timezone": "Asia/Shanghai",
        "email": "candidate@example.com",
        "languages": [
            {"code": "zh-CN", "level": "native"},
            {"code": "en", "level": "working"},
        ],
        "skills": [
            {"name": "python", "level": 4},
            {"name": "data_annotation", "level": 4},
        ],
        "desired_roles": ["ai_data"],
        "minimum_hourly_rate": {"amount": 15, "currency": "USD"},
        "availability_hours_per_week": 20,
        "allowed_work_modes": ["remote"],
        "notification_channels": ["email"],
        "notification_frequency": "daily",
        "excluded_companies": [],
    }
