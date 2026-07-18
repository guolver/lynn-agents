#!/usr/bin/env python
"""CLI: generate synthetic candidate data using Faker and import into the store.

Usage:
    python scripts/generate_candidates.py
    python scripts/generate_candidates.py --count 500
    python scripts/generate_candidates.py --count 100 --opt-in-ratio 0.8
"""

from __future__ import annotations

import argparse
import random
import sys

from faker import Faker

from agent_hub.agents.global_part_time.service import AgentService
from agent_hub.database.config import create_repository

ACTOR = "cli:generate_candidates"

# Weighted pools for realistic distribution
COUNTRY_POOLS = [
    # (country_code, timezone, weight, native_lang)
    ("CN", "Asia/Shanghai", 20, "zh-CN"),
    ("IN", "Asia/Kolkata", 15, "hi"),
    ("US", "America/New_York", 10, "en"),
    ("US", "America/Chicago", 5, "en"),
    ("US", "America/Los_Angeles", 5, "en"),
    ("GB", "Europe/London", 6, "en"),
    ("DE", "Europe/Berlin", 5, "de"),
    ("BR", "America/Sao_Paulo", 6, "pt"),
    ("JP", "Asia/Tokyo", 5, "ja"),
    ("KR", "Asia/Seoul", 4, "ko"),
    ("PH", "Asia/Manila", 6, "en"),
    ("PL", "Europe/Warsaw", 4, "pl"),
    ("UA", "Europe/Kiev", 4, "uk"),
    ("NG", "Africa/Lagos", 3, "en"),
    ("AR", "America/Argentina/Buenos_Aires", 3, "es"),
    ("MX", "America/Mexico_City", 3, "es"),
    ("VN", "Asia/Ho_Chi_Minh", 3, "vi"),
    ("ID", "Asia/Jakarta", 3, "id"),
    ("EG", "Africa/Cairo", 2, "ar"),
    ("TR", "Europe/Istanbul", 2, "tr"),
    ("CA", "America/Toronto", 2, "en"),
    ("AU", "Australia/Sydney", 2, "en"),
    ("FR", "Europe/Paris", 2, "fr"),
    ("ES", "Europe/Madrid", 2, "es"),
    ("IT", "Europe/Rome", 2, "it"),
]

SKILL_POOLS = {
    "engineering": [
        "python", "javascript", "typescript", "java", "go", "rust", "c++",
        "react", "vue", "angular", "node.js", "django", "fastapi", "spring",
        "docker", "kubernetes", "aws", "gcp", "azure", "terraform",
        "postgresql", "mongodb", "redis", "elasticsearch",
        "git", "ci_cd", "linux", "graphql", "rest_api",
    ],
    "data": [
        "python", "sql", "pandas", "spark", "airflow", "dbt",
        "data_annotation", "machine_learning", "deep_learning",
        "pytorch", "tensorflow", "scikit_learn", "nlp", "computer_vision",
        "data_visualization", "tableau", "power_bi", "r", "statistics",
    ],
    "design": [
        "figma", "sketch", "adobe_xd", "photoshop", "illustrator",
        "ui_design", "ux_research", "prototyping", "design_systems",
        "html", "css", "responsive_design",
    ],
    "content": [
        "copywriting", "content_strategy", "seo", "social_media",
        "technical_writing", "translation", "editing", "proofreading",
        "blog_writing", "email_marketing",
    ],
    "qa": [
        "manual_testing", "automation_testing", "selenium", "cypress",
        "api_testing", "performance_testing", "security_testing",
        "test_planning", "jira", "python",
    ],
}

ROLE_POOLS = {
    "engineering": [
        "backend_engineer", "frontend_engineer", "fullstack_engineer",
        "devops_engineer", "mobile_developer", "data_engineer",
    ],
    "data": [
        "data_scientist", "ml_engineer", "data_analyst",
        "ai_data", "data_engineer",
    ],
    "design": ["ui_designer", "ux_designer", "product_designer", "graphic_designer"],
    "content": ["content_writer", "technical_writer", "translator", "copywriter"],
    "qa": ["qa_engineer", "sdet", "test_lead"],
}

LANGUAGE_LEVELS = ["native", "fluent", "working", "basic"]

# Additional languages candidates might know
EXTRA_LANGUAGES = [
    ("en", 0.7), ("zh-CN", 0.05), ("es", 0.1), ("fr", 0.08),
    ("de", 0.06), ("pt", 0.05), ("ja", 0.03), ("ko", 0.03),
    ("ru", 0.04), ("ar", 0.03), ("hi", 0.03),
]


def generate_candidate(fake: Faker) -> dict:
    """Generate a single synthetic candidate payload."""
    # Pick country/timezone
    countries, timezones, weights, native_langs = zip(*COUNTRY_POOLS)
    idx = random.choices(range(len(countries)), weights=weights, k=1)[0]
    country = countries[idx]
    timezone = timezones[idx]
    native_lang = native_langs[idx]

    # Pick a career track
    track = random.choice(list(SKILL_POOLS.keys()))

    # Skills: 2-6 from the track
    track_skills = random.sample(
        SKILL_POOLS[track], k=min(random.randint(2, 6), len(SKILL_POOLS[track]))
    )
    skills = [{"name": s, "level": random.randint(2, 5)} for s in track_skills]

    # Desired roles: 1-3 from the track
    track_roles = ROLE_POOLS[track]
    desired_roles = random.sample(track_roles, k=min(random.randint(1, 3), len(track_roles)))

    # Languages: native + possibly English + maybe one more
    languages = [{"code": native_lang, "level": "native"}]
    if native_lang != "en" and random.random() < 0.75:
        level = random.choices(["fluent", "working", "basic"], weights=[3, 5, 2], k=1)[0]
        languages.append({"code": "en", "level": level})
    if random.random() < 0.3:
        extra = random.choice([l for l, _ in EXTRA_LANGUAGES if l != native_lang and l != "en"])
        languages.append({"code": extra, "level": random.choice(["basic", "working"])})

    # Work preferences
    hours = random.choice([10, 15, 20, 25, 30, 35, 40])
    work_modes = random.choice([
        ["remote"],
        ["remote"],
        ["remote"],
        ["remote", "hybrid"],
        ["hybrid"],
        ["remote", "hybrid", "onsite"],
    ])

    # Compensation
    base_rates = {
        "engineering": (20, 80),
        "data": (25, 90),
        "design": (20, 60),
        "content": (10, 40),
        "qa": (15, 50),
    }
    rate_min, rate_max = base_rates[track]
    # Adjust by country (rough purchasing-power factor)
    high_cost = {"US", "GB", "DE", "CA", "AU", "FR", "IT", "ES", "JP", "KR"}
    mid_cost = {"CN", "BR", "PL", "AR", "MX", "TR"}
    if country in high_cost:
        factor = random.uniform(0.8, 1.2)
    elif country in mid_cost:
        factor = random.uniform(0.4, 0.7)
    else:
        factor = random.uniform(0.2, 0.5)

    hourly_rate = round(random.uniform(rate_min, rate_max) * factor, 2)
    currency = random.choices(["USD", "EUR", "GBP"], weights=[7, 2, 1], k=1)[0]

    # Notification preferences
    channels = random.choice([
        ["email"],
        ["email"],
        ["email", "in_app"],
        ["in_app"],
        ["email", "telegram"],
        ["telegram"],
    ])
    frequency = random.choices(["daily", "weekly", "paused"], weights=[5, 4, 1], k=1)[0]

    # Excluded companies (most candidates have none)
    excluded = []
    if random.random() < 0.15:
        excluded = random.sample(
            ["Google", "Meta", "Amazon", "Microsoft", "Apple", "Tesla", "ByteDance"],
            k=random.randint(1, 3),
        )

    return {
        "country": country,
        "timezone": timezone,
        "email": fake.email(),
        "languages": languages,
        "skills": skills,
        "desired_roles": desired_roles,
        "minimum_hourly_rate": {"amount": hourly_rate, "currency": currency},
        "availability_hours_per_week": hours,
        "allowed_work_modes": work_modes,
        "notification_channels": channels,
        "notification_frequency": frequency,
        "excluded_companies": excluded,
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Generate synthetic candidate data")
    parser.add_argument("--count", type=int, default=200, help="Number of candidates to generate")
    parser.add_argument(
        "--opt-in-ratio",
        type=float,
        default=0.6,
        help="Fraction of candidates to auto opt-in (0.0-1.0)",
    )
    parser.add_argument("--seed", type=int, default=42, help="Random seed for reproducibility")
    args = parser.parse_args(argv)

    if not 0.0 <= args.opt_in_ratio <= 1.0:
        print("--opt-in-ratio must be between 0.0 and 1.0", file=sys.stderr)
        sys.exit(1)

    random.seed(args.seed)
    fake = Faker()
    Faker.seed(args.seed)

    repo = create_repository()
    service = AgentService(repo)

    # Check existing candidates
    existing = repo.list("candidate")
    print(f"Existing candidates in store: {len(existing)}")

    print(f"Generating {args.count} synthetic candidates (seed={args.seed})...")
    created = 0
    opted_in = 0

    for i in range(args.count):
        payload = generate_candidate(fake)
        candidate = service.create_candidate(payload, ACTOR)

        # Randomly opt-in based on ratio
        if random.random() < args.opt_in_ratio:
            service.set_consent(candidate["id"], True, ACTOR, "synthetic-v1")
            opted_in += 1

        created += 1
        if (i + 1) % 50 == 0:
            print(f"  ... {i + 1}/{args.count}")

    print(f"\n--- Generation Result ---")
    print(f"Created:    {created}")
    print(f"Opted-in:   {opted_in}")
    print(f"Opted-out:  {created - opted_in}")
    print(f"Total now:  {len(existing) + created}")


if __name__ == "__main__":
    main()
