# Skill Knowledge Graph Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Neo4j-backed skill knowledge graph that normalizes skill aliases and expands skills to parent categories, improving match recall and generating explainable recommendation reasons.

**Architecture:** `SkillGraphService` wraps a Neo4j driver, exposing `resolve()` (alias → canonical name) and `expand()` (names → canonical + parent categories). `domain.py`'s `_skill_score` accepts an optional `expand_fn` to integrate expansion. Seed data covers ~45 software development skills across 6 categories.

**Tech Stack:** Neo4j 5.x (Docker), `neo4j` Python driver, `testcontainers[neo4j]` for tests.

---

## File Structure

```
src/agent_hub/skill_graph/
├── __init__.py              # Re-export SkillGraphService
├── config.py                # Neo4j connection config (env-based)
├── seed.py                  # SKILL_GRAPH_SEED dict
└── service.py               # SkillGraphService (resolve, expand, seed)

tests/
├── test_skill_graph.py      # Neo4j integration tests (skipped without Docker)
└── test_domain.py           # Modified: add _skill_score expansion tests

src/agent_hub/agents/global_part_time/
├── domain.py                # Modified: _skill_score gains expand_fn param
└── service.py               # Modified: inject expand_fn into score_match

src/agent_hub/app.py         # Modified: init SkillGraphService at startup
pyproject.toml               # Modified: add neo4j + testcontainers deps
```

---

### Task 1: Add Dependencies

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add neo4j driver and testcontainers to pyproject.toml**

In `pyproject.toml`, add `neo4j` to runtime dependencies and `testcontainers[neo4j]` to dev dependencies:

```toml
dependencies = [
  "alembic>=1.16,<2",
  "fastapi>=0.115,<1",
  "neo4j>=5.20,<6",
  "pydantic>=2.9,<3",
  "psycopg[binary]>=3.2,<4",
  "sqlalchemy>=2.0,<3",
  "uvicorn[standard]>=0.30,<1",
]

[project.optional-dependencies]
dev = ["httpx>=0.27,<1", "pytest>=8.3,<9", "ruff>=0.8,<1", "testcontainers[neo4j]>=4.9,<5"]
```

- [ ] **Step 2: Install dependencies**

Run: `source .venv/bin/activate && pip install -e ".[dev]"`
Expected: Installs successfully, `neo4j` and `testcontainers` are available.

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml
git commit -m "feat: add neo4j and testcontainers dependencies"
```

---

### Task 2: Neo4j Connection Config

**Files:**
- Create: `src/agent_hub/skill_graph/__init__.py`
- Create: `src/agent_hub/skill_graph/config.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_skill_graph.py`:

```python
import os
import unittest


NEO4J_AVAILABLE = False
try:
    from testcontainers.neo4j import Neo4jContainer

    NEO4J_AVAILABLE = True
except Exception:
    pass


@unittest.skipUnless(NEO4J_AVAILABLE, "testcontainers[neo4j] or Docker not available")
class Neo4jConfigTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.container = Neo4jContainer("neo4j:5")
        cls.container.start()
        cls.bolt_url = cls.container.get_connection_url()

    @classmethod
    def tearDownClass(cls):
        cls.container.stop()

    def test_create_driver_connects(self):
        from agent_hub.skill_graph.config import create_neo4j_driver

        driver = create_neo4j_driver(self.bolt_url, auth=("neo4j", "test"))
        driver.verify_connectivity()
        driver.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_skill_graph.py::Neo4jConfigTest::test_create_driver_connects -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'agent_hub.skill_graph'`

- [ ] **Step 3: Create the skill_graph package and config module**

Create `src/agent_hub/skill_graph/__init__.py`:

```python
"""Skill knowledge graph backed by Neo4j."""
```

Create `src/agent_hub/skill_graph/config.py`:

```python
"""Neo4j connection factory."""

from __future__ import annotations

import os
from typing import Any

import neo4j


def create_neo4j_driver(
    uri: str | None = None,
    auth: tuple[str, str] | None = None,
    **kwargs: Any,
) -> neo4j.Driver:
    """Create a Neo4j driver from explicit args or environment variables.

    Env vars: NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD.
    """
    resolved_uri = uri or os.getenv("NEO4J_URI", "bolt://localhost:7687")
    resolved_auth = auth or (
        os.getenv("NEO4J_USER", "neo4j"),
        os.getenv("NEO4J_PASSWORD", "password"),
    )
    return neo4j.GraphDatabase.driver(resolved_uri, auth=resolved_auth, **kwargs)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_skill_graph.py::Neo4jConfigTest::test_create_driver_connects -v`
Expected: PASS (or SKIP if Docker not available)

- [ ] **Step 5: Commit**

```bash
git add src/agent_hub/skill_graph/__init__.py src/agent_hub/skill_graph/config.py tests/test_skill_graph.py
git commit -m "feat: add Neo4j connection config with env-based factory"
```

---

### Task 3: Seed Data

**Files:**
- Create: `src/agent_hub/skill_graph/seed.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_skill_graph.py`:

```python
@unittest.skipUnless(NEO4J_AVAILABLE, "testcontainers[neo4j] or Docker not available")
class SeedDataTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.container = Neo4jContainer("neo4j:5")
        cls.container.start()
        cls.bolt_url = cls.container.get_connection_url()

    @classmethod
    def tearDownClass(cls):
        cls.container.stop()

    def test_seed_data_structure_is_valid(self):
        from agent_hub.skill_graph.seed import SKILL_GRAPH_SEED

        for category, data in SKILL_GRAPH_SEED.items():
            self.assertIsInstance(category, str)
            self.assertIn("skills", data)
            self.assertIsInstance(data["skills"], list)
            self.assertTrue(len(data["skills"]) > 0, f"{category} has no skills")
            aliases = data.get("aliases", {})
            for skill_name, alias_list in aliases.items():
                self.assertIn(skill_name, data["skills"], f"alias key {skill_name} not in skills")
                self.assertIsInstance(alias_list, list)

    def test_seed_has_expected_categories(self):
        from agent_hub.skill_graph.seed import SKILL_GRAPH_SEED

        expected = {"前端开发", "后端开发", "数据库", "容器与云", "移动开发", "数据与AI"}
        self.assertEqual(set(SKILL_GRAPH_SEED.keys()), expected)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_skill_graph.py::SeedDataTest -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'agent_hub.skill_graph.seed'`

- [ ] **Step 3: Create seed data module**

Create `src/agent_hub/skill_graph/seed.py`:

```python
"""Seed data for the skill knowledge graph.

Each top-level key is a Category node. Its ``skills`` list contains canonical
Skill nodes that have a ``CHILD_OF`` relationship to the category. The
``aliases`` dict maps a canonical skill name to a list of alternative names;
each alias becomes a Skill node linked via ``ALIAS_OF`` to the canonical node.
"""

from __future__ import annotations

SKILL_GRAPH_SEED: dict[str, dict] = {
    "前端开发": {
        "skills": [
            "React", "Vue", "Angular", "TypeScript", "JavaScript",
            "HTML/CSS", "Next.js", "Tailwind CSS", "Svelte",
        ],
        "aliases": {
            "React": ["React.js", "ReactJS", "react"],
            "Vue": ["Vue.js", "VueJS", "vue"],
            "Angular": ["AngularJS", "angular"],
            "TypeScript": ["TS", "ts"],
            "JavaScript": ["JS", "js", "ES6"],
            "Next.js": ["NextJS", "nextjs"],
            "Tailwind CSS": ["Tailwind", "tailwind"],
        },
    },
    "后端开发": {
        "skills": [
            "Python", "Java", "Go", "Node.js", "C#",
            "Ruby", "PHP", "Rust", "Scala",
        ],
        "aliases": {
            "Go": ["Golang", "golang"],
            "Node.js": ["NodeJS", "nodejs", "node"],
            "C#": ["CSharp", "C Sharp", "csharp"],
            "Ruby": ["ruby"],
            "PHP": ["php"],
            "Rust": ["rust"],
        },
    },
    "数据库": {
        "skills": [
            "PostgreSQL", "MySQL", "MongoDB", "Redis",
            "Elasticsearch", "SQLite", "Cassandra",
        ],
        "aliases": {
            "PostgreSQL": ["Postgres", "PG", "pg", "postgres"],
            "MySQL": ["mysql"],
            "MongoDB": ["Mongo", "mongo"],
            "Redis": ["redis"],
            "Elasticsearch": ["ES", "es", "ElasticSearch"],
        },
    },
    "容器与云": {
        "skills": [
            "Docker", "Kubernetes", "AWS", "GCP",
            "Azure", "Terraform", "Linux",
        ],
        "aliases": {
            "Kubernetes": ["K8s", "k8s"],
            "AWS": ["Amazon Web Services", "aws"],
            "GCP": ["Google Cloud Platform", "Google Cloud", "gcp"],
            "Azure": ["azure", "Microsoft Azure"],
            "Terraform": ["TF", "terraform"],
            "Docker": ["docker"],
        },
    },
    "移动开发": {
        "skills": [
            "iOS", "Android", "React Native", "Flutter",
            "Swift", "Kotlin",
        ],
        "aliases": {
            "React Native": ["RN", "react-native", "ReactNative"],
            "Flutter": ["flutter"],
            "iOS": ["ios", "IOS"],
            "Android": ["android"],
        },
    },
    "数据与AI": {
        "skills": [
            "TensorFlow", "PyTorch", "Pandas", "Spark",
            "SQL", "Scikit-learn", "NumPy",
        ],
        "aliases": {
            "TensorFlow": ["TF", "tensorflow"],
            "Scikit-learn": ["Sklearn", "sklearn", "scikit-learn"],
            "PyTorch": ["pytorch"],
            "Pandas": ["pandas"],
            "NumPy": ["numpy", "Numpy"],
        },
    },
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_skill_graph.py::SeedDataTest -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/agent_hub/skill_graph/seed.py tests/test_skill_graph.py
git commit -m "feat: add skill knowledge graph seed data for 6 dev categories"
```

---

### Task 4: SkillGraphService — seed(), resolve(), expand()

**Files:**
- Create: `src/agent_hub/skill_graph/service.py`
- Modify: `src/agent_hub/skill_graph/__init__.py`
- Modify: `tests/test_skill_graph.py`

- [ ] **Step 1: Write failing tests for seed and resolve**

Append to `tests/test_skill_graph.py`:

```python
@unittest.skipUnless(NEO4J_AVAILABLE, "testcontainers[neo4j] or Docker not available")
class SkillGraphServiceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.container = Neo4jContainer("neo4j:5")
        cls.container.start()
        bolt_url = cls.container.get_connection_url()
        from agent_hub.skill_graph.config import create_neo4j_driver
        from agent_hub.skill_graph.service import SkillGraphService

        cls.driver = create_neo4j_driver(bolt_url, auth=("neo4j", "test"))
        cls.service = SkillGraphService(cls.driver)
        cls.service.seed()

    @classmethod
    def tearDownClass(cls):
        cls.driver.close()
        cls.container.stop()

    def test_resolve_canonical_returns_self(self):
        self.assertEqual(self.service.resolve("React"), "React")

    def test_resolve_alias_returns_canonical(self):
        self.assertEqual(self.service.resolve("K8s"), "Kubernetes")
        self.assertEqual(self.service.resolve("ReactJS"), "React")
        self.assertEqual(self.service.resolve("Golang"), "Go")

    def test_resolve_unknown_returns_none(self):
        self.assertIsNone(self.service.resolve("NonExistentSkill"))

    def test_expand_returns_canonical_and_categories(self):
        result = self.service.expand(["K8s", "React.js"])
        self.assertIn("Kubernetes", result)
        self.assertIn("React", result)
        self.assertIn("容器与云", result)
        self.assertIn("前端开发", result)

    def test_expand_empty_returns_empty(self):
        result = self.service.expand([])
        self.assertEqual(result, set())

    def test_expand_unknown_skill_ignored(self):
        result = self.service.expand(["NonExistent"])
        self.assertEqual(result, set())

    def test_seed_is_idempotent(self):
        self.service.seed()
        self.service.seed()
        self.assertEqual(self.service.resolve("K8s"), "Kubernetes")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_skill_graph.py::SkillGraphServiceTest -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'agent_hub.skill_graph.service'`

- [ ] **Step 3: Implement SkillGraphService**

Create `src/agent_hub/skill_graph/service.py`:

```python
"""Skill knowledge graph service backed by Neo4j."""

from __future__ import annotations

import neo4j

from .seed import SKILL_GRAPH_SEED


class SkillGraphService:
    """Provides alias resolution and category expansion over a Neo4j skill graph."""

    def __init__(self, driver: neo4j.Driver):
        self.driver = driver

    def seed(self) -> None:
        """Write seed data into Neo4j using MERGE (idempotent)."""
        with self.driver.session() as session:
            for category, data in SKILL_GRAPH_SEED.items():
                session.run(
                    "MERGE (c:Category {name: $name})",
                    name=category,
                )
                for skill_name in data["skills"]:
                    session.run(
                        "MERGE (s:Skill {name: $name})",
                        name=skill_name,
                    )
                    session.run(
                        "MATCH (s:Skill {name: $skill}), (c:Category {name: $cat}) "
                        "MERGE (s)-[:CHILD_OF]->(c)",
                        skill=skill_name,
                        cat=category,
                    )
                for canonical, aliases in data.get("aliases", {}).items():
                    for alias in aliases:
                        session.run(
                            "MERGE (a:Skill {name: $alias})",
                            alias=alias,
                        )
                        session.run(
                            "MATCH (a:Skill {name: $alias}), (c:Skill {name: $canonical}) "
                            "MERGE (a)-[:ALIAS_OF]->(c)",
                            alias=alias,
                            canonical=canonical,
                        )

    def resolve(self, name: str) -> str | None:
        """Resolve an alias to its canonical skill name.

        Returns the canonical name if ``name`` is an alias, ``name`` itself if
        it is already canonical, or ``None`` if the skill is unknown.
        """
        with self.driver.session() as session:
            result = session.run(
                "OPTIONAL MATCH (s:Skill {name: $name})-[:ALIAS_OF]->(canonical:Skill) "
                "WITH s, canonical "
                "WHERE s IS NOT NULL "
                "RETURN coalesce(canonical.name, s.name) AS resolved",
                name=name,
            )
            record = result.single()
            if record is None:
                return None
            return record["resolved"]

    def expand(self, names: list[str]) -> set[str]:
        """Batch resolve aliases and expand to parent categories.

        Returns a set containing canonical skill names and their parent
        category names.  Unknown names are silently ignored.
        """
        if not names:
            return set()
        with self.driver.session() as session:
            result = session.run(
                "UNWIND $names AS input "
                "MATCH (s:Skill {name: input}) "
                "OPTIONAL MATCH (s)-[:ALIAS_OF]->(canonical:Skill) "
                "WITH coalesce(canonical, s) AS resolved "
                "OPTIONAL MATCH (resolved)-[:CHILD_OF]->(cat:Category) "
                "RETURN collect(DISTINCT resolved.name) + collect(DISTINCT cat.name) AS expanded",
                names=names,
            )
            record = result.single()
            if record is None:
                return set()
            return set(record["expanded"])
```

Update `src/agent_hub/skill_graph/__init__.py`:

```python
"""Skill knowledge graph backed by Neo4j."""

from .service import SkillGraphService

__all__ = ["SkillGraphService"]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_skill_graph.py::SkillGraphServiceTest -v`
Expected: All 7 tests PASS (or all SKIP if Docker not available)

- [ ] **Step 5: Run ruff**

Run: `ruff check src/agent_hub/skill_graph/ tests/test_skill_graph.py && ruff format src/agent_hub/skill_graph/ tests/test_skill_graph.py`

- [ ] **Step 6: Commit**

```bash
git add src/agent_hub/skill_graph/ tests/test_skill_graph.py
git commit -m "feat: implement SkillGraphService with resolve, expand, and seed"
```

---

### Task 5: Integrate with domain.py — _skill_score expansion

**Files:**
- Modify: `src/agent_hub/agents/global_part_time/domain.py:169-177` (`_skill_score`)
- Modify: `src/agent_hub/agents/global_part_time/domain.py:179-217` (`score_match`)
- Modify: `tests/test_domain.py`

- [ ] **Step 1: Write failing tests for expanded _skill_score**

Append to `tests/test_domain.py`:

```python
class SkillScoreExpansionTest(unittest.TestCase):
    def test_skill_score_without_expand_fn_is_backward_compatible(self):
        candidate = {"skills": [{"name": "Python"}, {"name": "React"}]}
        job = {"skills": ["Python", "React"]}
        score, breakdown, reasons = score_match(candidate, job)
        self.assertEqual(breakdown["skills"], 1.0)

    def test_skill_score_with_expand_fn_boosts_indirect_matches(self):
        candidate = {"skills": [{"name": "React"}]}
        job = {"skills": ["前端开发"]}

        def mock_expand(names):
            mapping = {"React": {"React", "前端开发"}}
            result = set()
            for n in names:
                result.update(mapping.get(n, set()))
            return result

        score, breakdown, reasons = score_match(candidate, job, expand_fn=mock_expand)
        self.assertGreater(breakdown["skills"], 0.0)
        self.assertLessEqual(breakdown["skills"], 0.6)

    def test_skill_score_direct_match_preferred_over_indirect(self):
        candidate = {"skills": [{"name": "Python"}, {"name": "React"}]}
        job = {"skills": ["Python", "前端开发"]}

        def mock_expand(names):
            return {"Python", "React", "前端开发", "后端开发"}

        score, breakdown, reasons = score_match(candidate, job, expand_fn=mock_expand)
        # Python direct (1.0) + 前端开发 indirect (0.6) → (1.0 + 0.6) / 2 = 0.8
        self.assertAlmostEqual(breakdown["skills"], 0.8, places=2)

    def test_score_match_reasons_include_skill_expansion(self):
        candidate = {
            "consent_status": "opted_in",
            "country": "CN",
            "timezone": "Asia/Shanghai",
            "languages": [{"code": "en"}],
            "skills": [{"name": "React"}],
            "desired_roles": [],
            "minimum_hourly_rate": None,
            "availability_hours_per_week": 40,
            "allowed_work_modes": ["remote"],
            "excluded_companies": [],
        }
        job = {
            "title_original": "Frontend Dev",
            "company_name": "Test",
            "description_original": "Build UIs",
            "canonical_url": "https://example.com/1",
            "status": "active",
            "review_status": "not_required",
            "risk_score": 0.0,
            "work_mode": "remote",
            "countries_allowed": ["GLOBAL"],
            "timezone_requirements": [],
            "languages": ["en"],
            "skills": ["前端开发"],
            "categories": [],
            "hours_per_week_min": 10,
            "compensation_max": None,
            "compensation_currency": "USD",
            "quality_score": 0.8,
        }

        def mock_expand(names):
            return {"React", "前端开发"}

        score, breakdown, reasons = score_match(candidate, job, expand_fn=mock_expand)
        has_expansion_reason = any("扩展" in r or "相关" in r for r in reasons)
        self.assertTrue(has_expansion_reason, f"Expected expansion reason in {reasons}")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_domain.py::SkillScoreExpansionTest -v`
Expected: FAIL — `score_match` does not accept `expand_fn` parameter.

- [ ] **Step 3: Modify _skill_score and score_match in domain.py**

In `src/agent_hub/agents/global_part_time/domain.py`, replace `_skill_score` (lines 169-176):

```python
def _skill_score(
    candidate: dict[str, Any],
    job: dict[str, Any],
    expand_fn: Callable[[list[str]], set[str]] | None = None,
) -> tuple[float, list[str], list[str]]:
    required = {_norm(x) for x in job.get("skills") or []}
    if not required:
        return 0.5, [], []
    raw_owned = [x["name"] if isinstance(x, dict) else x for x in candidate.get("skills") or []]
    owned = {_norm(x) for x in raw_owned}
    if expand_fn:
        expanded = {_norm(x) for x in expand_fn(raw_owned)}
    else:
        expanded = set()
    direct = sorted(required & owned)
    indirect = sorted((required & expanded) - direct)
    score = (len(direct) + len(indirect) * 0.6) / len(required)
    return min(score, 1.0), direct, indirect
```

Add `Callable` to the imports at the top of `domain.py`:

```python
from typing import Any, Callable
```

Replace `score_match` (lines 179-217) to accept and forward `expand_fn`, and generate skill-expansion reasons:

```python
def score_match(
    candidate: dict[str, Any],
    job: dict[str, Any],
    expand_fn: Callable[[list[str]], set[str]] | None = None,
) -> tuple[float, dict[str, float], list[str]]:
    """按照版本化权重生成可复现总分、分项分数和面向用户的理由。"""
    skill, direct_skills, indirect_skills = _skill_score(candidate, job, expand_fn)
    required_langs = set(job.get("languages") or [])
    owned_langs = {
        x["code"] if isinstance(x, dict) else x for x in candidate.get("languages") or []
    }
    language = len(required_langs & owned_langs) / len(required_langs) if required_langs else 1.0
    countries = set(job.get("countries_allowed") or [])
    location = (
        1.0 if not countries or "GLOBAL" in countries or candidate.get("country") in countries
        else 0.0
    )
    timezone = float(
        timezone_matches(candidate.get("timezone"), job.get("timezone_requirements") or [])
    )
    location_timezone = 0.7 * location + 0.3 * timezone
    minimum = (candidate.get("minimum_hourly_rate") or {}).get("amount")
    maximum = job.get("compensation_max")
    compensation = (
        0.5 if maximum is None or minimum is None
        else min(float(maximum) / max(float(minimum), 1), 1.0)
    )
    desired = set(candidate.get("desired_roles") or [])
    categories = set(job.get("categories") or [])
    preference = 1.0 if not desired or desired & categories else 0.4
    quality = float(job.get("quality_score", 0.5))
    freshness_quality = min(max(quality, 0.0), 1.0)
    breakdown = {
        "skills": round(skill, 4),
        "language": round(language, 4),
        "location_timezone": round(location_timezone, 4),
        "compensation": round(compensation, 4),
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
    if location_timezone >= 0.7:
        reasons.append("地区与工作时区满足要求")
    if compensation >= 1:
        reasons.append("薪资达到最低期望")
    if preference >= 1:
        reasons.append("职位类别符合你的偏好")
    return total, breakdown, reasons or ["该职位通过了你的全部硬性条件"]
```

- [ ] **Step 4: Run all domain tests**

Run: `python -m pytest tests/test_domain.py -v`
Expected: All tests PASS, including original `DomainRulesTest` (backward compatibility).

- [ ] **Step 5: Commit**

```bash
git add src/agent_hub/agents/global_part_time/domain.py tests/test_domain.py
git commit -m "feat: add expand_fn support to _skill_score and score_match"
```

---

### Task 6: Wire SkillGraphService into service.py and app.py

**Files:**
- Modify: `src/agent_hub/agents/global_part_time/service.py:209-255` (`run_matches`)
- Modify: `src/agent_hub/app.py`

- [ ] **Step 1: Modify AgentService to accept an optional expand_fn**

In `src/agent_hub/agents/global_part_time/service.py`, update `__init__` and `run_matches`:

Change the constructor (line 35-36):

```python
class AgentService:
    """实现职位采集、候选匹配、审批和通知的完整业务用例。"""

    def __init__(
        self,
        repository: RepositoryProtocol,
        expand_fn: Callable[[list[str]], set[str]] | None = None,
    ):
        self.repo = repository
        self.expand_fn = expand_fn
```

Add `Callable` to imports at the top:

```python
from typing import Any, Callable
```

In `run_matches` (line 231), change the `score_match` call:

```python
            score, breakdown, reasons = score_match(candidate, job, self.expand_fn)
```

- [ ] **Step 2: Modify app.py to create and inject SkillGraphService**

In `src/agent_hub/app.py`, update `create_app` to optionally initialize the skill graph:

Add import at top:

```python
import logging
import os

logger = logging.getLogger(__name__)
```

After `repo = repository or create_repository()` (line 41), add skill graph initialization:

```python
    expand_fn = None
    neo4j_uri = os.getenv("NEO4J_URI")
    if neo4j_uri:
        try:
            from .skill_graph.config import create_neo4j_driver
            from .skill_graph.service import SkillGraphService

            neo4j_driver = create_neo4j_driver(neo4j_uri)
            skill_graph = SkillGraphService(neo4j_driver)
            skill_graph.seed()
            expand_fn = skill_graph.expand
            logger.info("Skill graph initialized from Neo4j at %s", neo4j_uri)
        except Exception:
            logger.warning("Failed to initialize skill graph, continuing without it", exc_info=True)
```

Change `AgentService` construction:

```python
    part_time_service = AgentService(repo, expand_fn=expand_fn)
```

- [ ] **Step 3: Run existing tests to verify backward compatibility**

Run: `python -m pytest tests/test_service.py tests/test_api.py tests/test_platform.py tests/test_domain.py -v`
Expected: All PASS — without `NEO4J_URI` set, `expand_fn` is `None`, behavior unchanged.

- [ ] **Step 4: Commit**

```bash
git add src/agent_hub/agents/global_part_time/service.py src/agent_hub/app.py
git commit -m "feat: wire SkillGraphService into matching pipeline via expand_fn"
```

---

### Task 7: End-to-End Integration Test

**Files:**
- Modify: `tests/test_skill_graph.py`

- [ ] **Step 1: Write end-to-end test**

Append to `tests/test_skill_graph.py`:

```python
@unittest.skipUnless(NEO4J_AVAILABLE, "testcontainers[neo4j] or Docker not available")
class EndToEndSkillMatchTest(unittest.TestCase):
    """Test the full flow: seed → expand → score_match."""

    @classmethod
    def setUpClass(cls):
        cls.container = Neo4jContainer("neo4j:5")
        cls.container.start()
        bolt_url = cls.container.get_connection_url()
        from agent_hub.skill_graph.config import create_neo4j_driver
        from agent_hub.skill_graph.service import SkillGraphService

        cls.driver = create_neo4j_driver(bolt_url, auth=("neo4j", "test"))
        cls.service = SkillGraphService(cls.driver)
        cls.service.seed()

    @classmethod
    def tearDownClass(cls):
        cls.driver.close()
        cls.container.stop()

    def test_alias_improves_match_score(self):
        from agent_hub.agents.global_part_time.domain import score_match

        candidate = {"skills": [{"name": "K8s"}, {"name": "ReactJS"}]}
        job = {"skills": ["Kubernetes", "React"]}

        # Without expansion: no match (different strings)
        _, breakdown_without, _ = score_match(candidate, job)
        self.assertEqual(breakdown_without["skills"], 0.0)

        # With expansion: aliases resolved
        _, breakdown_with, reasons = score_match(candidate, job, expand_fn=self.service.expand)
        self.assertGreater(breakdown_with["skills"], 0.0)

    def test_category_expansion_enables_indirect_match(self):
        from agent_hub.agents.global_part_time.domain import score_match

        candidate = {"skills": [{"name": "React"}, {"name": "Vue"}]}
        job = {"skills": ["前端开发"]}

        # Without expansion: no match
        _, breakdown_without, _ = score_match(candidate, job)
        self.assertEqual(breakdown_without["skills"], 0.0)

        # With expansion: React/Vue → 前端开发
        _, breakdown_with, reasons = score_match(candidate, job, expand_fn=self.service.expand)
        self.assertGreater(breakdown_with["skills"], 0.0)
        has_expansion = any("扩展" in r or "相关" in r for r in reasons)
        self.assertTrue(has_expansion, f"Expected expansion reason in {reasons}")

    def test_direct_match_scores_higher_than_indirect(self):
        from agent_hub.agents.global_part_time.domain import score_match

        candidate = {"skills": [{"name": "Python"}, {"name": "React"}]}

        # Job requires Python (direct) and 前端开发 (indirect via React)
        job = {"skills": ["Python", "前端开发"]}
        _, breakdown, _ = score_match(candidate, job, expand_fn=self.service.expand)

        # Direct(Python)=1.0 + Indirect(前端开发)=0.6 → avg = 0.8
        self.assertAlmostEqual(breakdown["skills"], 0.8, places=1)
```

- [ ] **Step 2: Run the test**

Run: `python -m pytest tests/test_skill_graph.py::EndToEndSkillMatchTest -v`
Expected: All 3 tests PASS (or SKIP if Docker not available)

- [ ] **Step 3: Run full test suite**

Run: `python -m pytest tests/ -v`
Expected: All tests PASS.

- [ ] **Step 4: Run linter on all changed files**

Run: `ruff check src/agent_hub/skill_graph/ src/agent_hub/agents/global_part_time/domain.py src/agent_hub/agents/global_part_time/service.py src/agent_hub/app.py tests/test_skill_graph.py tests/test_domain.py && ruff format src/agent_hub/skill_graph/ src/agent_hub/agents/global_part_time/domain.py src/agent_hub/agents/global_part_time/service.py src/agent_hub/app.py tests/test_skill_graph.py tests/test_domain.py`

- [ ] **Step 5: Commit**

```bash
git add tests/test_skill_graph.py
git commit -m "test: add end-to-end skill graph integration tests"
```

---

## Summary

| Task | What it does |
|------|-------------|
| 1 | Add `neo4j` and `testcontainers` dependencies |
| 2 | Neo4j connection config with env-based factory |
| 3 | Seed data for 6 software development categories |
| 4 | `SkillGraphService` with `resolve()`, `expand()`, `seed()` |
| 5 | `_skill_score` and `score_match` gain `expand_fn` + expansion reasons |
| 6 | Wire into `service.py` and `app.py` (backward compatible) |
| 7 | End-to-end integration tests |
