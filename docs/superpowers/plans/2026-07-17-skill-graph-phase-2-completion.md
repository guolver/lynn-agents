# Skill Graph Phase 2 Completion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete Phase 2 with bounded weighted Neo4j traversal, deterministic path evidence, whole-batch fallback, match JSON persistence, and local Neo4j development support.

**Architecture:** `SkillGraphService` returns immutable typed expansion evidence while retaining the existing set-based `expand()` compatibility API. Pure domain code selects the best directionally valid path for each job requirement; `AgentService` scores an eligible batch in memory and persists either one consistent graph-scored batch or one consistent direct-fallback batch.

**Tech Stack:** Python 3.10+, Neo4j 5.x, `neo4j` Python driver, `testcontainers[neo4j]`, FastAPI, Docker Compose, unittest/pytest, Ruff.

## Global Constraints

- Maximum graph traversal depth is exactly `1` or `2`; the default is `2`.
- Direct and alias matches weigh `1.00`; `REQUIRES` weighs `0.75`; `CHILD_OF` weighs `0.65`; `RELATED_TO` weighs `0.40`.
- A two-hop path weighs `min(edge_weights) * 0.50`.
- Alias normalization does not consume traversal depth.
- `CHILD_OF` matches candidate concrete skills to job categories only.
- `REQUIRES` is traversed from the required job skill to a candidate prerequisite only.
- `RELATED_TO` is symmetric for matching even though each seed pair is stored once.
- A path may not repeat a node; unknown skills do not expand.
- Only the deterministic best path per required skill contributes to scoring and evidence.
- Graph failures cause the entire eligible batch to be recomputed before any match is persisted.
- Evidence is stored in match JSON under `skill_graph_evidence`; normalized evidence tables remain Phase 4 work.
- No exception message, credential, URI, or stack trace is stored in match JSON.
- The legacy `expand(names) -> set[str]` and `score_match(...) -> tuple[float, dict, list]` interfaces remain backward compatible.

---

## File Structure

| File | Responsibility |
| --- | --- |
| `agent_hub/skill_graph/types.py` | Immutable expansion/evidence result types and stable JSON conversion |
| `agent_hub/skill_graph/seed.py` | Canonical categories, aliases, curated relations, and pure seed validation |
| `agent_hub/skill_graph/service.py` | Idempotent relationship seeding and bounded Neo4j evidence queries |
| `agent_hub/skill_graph/__init__.py` | Public graph type and service exports |
| `agent_hub/agents/global_part_time/domain.py` | Directional path selection and deterministic weighted skill scoring |
| `agent_hub/agents/global_part_time/service.py` | Whole-batch graph scoring/fallback and match evidence persistence |
| `agent_hub/app.py` | Inject the rich expansion callback while preserving lifecycle cleanup |
| `tests/test_skill_graph_types.py` | Type serialization and ordering unit tests |
| `tests/test_skill_graph_seed.py` | Pure seed validation tests without Docker |
| `tests/test_skill_graph.py` | Real Neo4j seed/traversal integration tests |
| `tests/test_domain.py` | Pure scoring, direction, weight, and tie-break tests |
| `tests/test_service.py` | Evidence persistence and batch fallback tests |
| `tests/test_app_skill_graph_lifecycle.py` | Rich callback injection/lifecycle tests |
| `compose.dev.yaml` | Local PostgreSQL, Redis, and Neo4j services |
| `.env.example` | Neo4j environment configuration |
| `Makefile` | Focused Neo4j development and test commands |
| `docs/dev-guide.md` | Local Neo4j setup, health, seeding, and testing instructions |

---

### Task 1: Add Typed Evidence Results and Validated Relation Seed

**Files:**
- Create: `agent_hub/skill_graph/types.py`
- Modify: `agent_hub/skill_graph/seed.py`
- Modify: `agent_hub/skill_graph/__init__.py`
- Create: `tests/test_skill_graph_types.py`
- Create: `tests/test_skill_graph_seed.py`

**Interfaces:**
- Produces: `ExpansionEvidence`, `ExpansionResult`, `SKILL_RELATIONS`, `validate_seed()`.
- `ExpansionResult.targets() -> set[str]` is consumed by the compatibility `expand()` implementation in Task 2.

- [ ] **Step 1: Write failing immutable-type and JSON tests**

Create `tests/test_skill_graph_types.py`:

```python
import unittest

from agent_hub.skill_graph.types import ExpansionEvidence, ExpansionResult


class ExpansionTypesTest(unittest.TestCase):
    def test_to_dict_is_stable_and_json_safe(self):
        evidence = ExpansionEvidence(
            input_skill="Kubernetes",
            canonical_skill="Kubernetes",
            target="Docker",
            target_kind="skill",
            relations=("REQUIRES",),
            nodes=("Kubernetes", "Docker"),
            depth=1,
            weight=0.75,
        )
        result = ExpansionResult((evidence,))

        self.assertEqual(result.targets(), {"Docker"})
        self.assertEqual(
            result.to_dict(),
            {
                "evidence": [
                    {
                        "input_skill": "Kubernetes",
                        "canonical_skill": "Kubernetes",
                        "target": "Docker",
                        "target_kind": "skill",
                        "relations": ["REQUIRES"],
                        "nodes": ["Kubernetes", "Docker"],
                        "depth": 1,
                        "weight": 0.75,
                    }
                ]
            },
        )

    def test_result_orders_evidence_deterministically(self):
        later = ExpansionEvidence("React", "React", "Vue", "skill", ("RELATED_TO",), ("React", "Vue"), 1, 0.4)
        earlier = ExpansionEvidence("React", "React", "Angular", "skill", ("RELATED_TO",), ("React", "Angular"), 1, 0.4)
        result = ExpansionResult.from_iterable([later, earlier])
        self.assertEqual([item.target for item in result.evidence], ["Angular", "Vue"])
```

- [ ] **Step 2: Run the type tests and verify RED**

Run: `.venv/bin/python -m pytest tests/test_skill_graph_types.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'agent_hub.skill_graph.types'`.

- [ ] **Step 3: Implement the immutable result types**

Create `agent_hub/skill_graph/types.py`:

```python
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Iterable, Literal


@dataclass(frozen=True)
class ExpansionEvidence:
    input_skill: str
    canonical_skill: str
    target: str
    target_kind: Literal["skill", "category"]
    relations: tuple[str, ...]
    nodes: tuple[str, ...]
    depth: int
    weight: float

    def to_dict(self) -> dict:
        value = asdict(self)
        value["relations"] = list(self.relations)
        value["nodes"] = list(self.nodes)
        return value


@dataclass(frozen=True)
class ExpansionResult:
    evidence: tuple[ExpansionEvidence, ...] = ()

    @classmethod
    def from_iterable(cls, values: Iterable[ExpansionEvidence]) -> "ExpansionResult":
        ordered = sorted(
            values,
            key=lambda item: (
                item.input_skill.casefold(),
                item.target.casefold(),
                -item.weight,
                item.depth,
                item.nodes,
                item.relations,
            ),
        )
        return cls(tuple(ordered))

    def targets(self) -> set[str]:
        return {item.target for item in self.evidence}

    def to_dict(self) -> dict:
        return {"evidence": [item.to_dict() for item in self.evidence]}
```

- [ ] **Step 4: Run type tests and verify GREEN**

Run: `.venv/bin/python -m pytest tests/test_skill_graph_types.py -v`

Expected: 2 tests PASS.

- [ ] **Step 5: Write failing seed validation tests**

Create `tests/test_skill_graph_seed.py`:

```python
import unittest

from agent_hub.skill_graph.seed import SKILL_GRAPH_SEED, SKILL_RELATIONS, validate_seed


class SkillGraphSeedValidationTest(unittest.TestCase):
    def test_checked_in_seed_is_valid(self):
        validate_seed(SKILL_GRAPH_SEED, SKILL_RELATIONS)

    def test_rejects_unknown_endpoint(self):
        with self.assertRaisesRegex(ValueError, "unknown relation endpoint: Missing"):
            validate_seed(SKILL_GRAPH_SEED, [
                {"from": "React", "type": "RELATED_TO", "to": "Missing"}
            ])

    def test_rejects_self_relation(self):
        with self.assertRaisesRegex(ValueError, "self relation: React"):
            validate_seed(SKILL_GRAPH_SEED, [
                {"from": "React", "type": "RELATED_TO", "to": "React"}
            ])

    def test_rejects_duplicate_relation(self):
        relation = {"from": "React", "type": "RELATED_TO", "to": "Vue"}
        with self.assertRaisesRegex(ValueError, "duplicate relation"):
            validate_seed(SKILL_GRAPH_SEED, [relation, relation])

    def test_rejects_requires_cycle(self):
        relations = [
            {"from": "React", "type": "REQUIRES", "to": "Vue"},
            {"from": "Vue", "type": "REQUIRES", "to": "React"},
        ]
        with self.assertRaisesRegex(ValueError, "REQUIRES cycle"):
            validate_seed(SKILL_GRAPH_SEED, relations)
```

- [ ] **Step 6: Run seed tests and verify RED**

Run: `.venv/bin/python -m pytest tests/test_skill_graph_seed.py -v`

Expected: FAIL because `SKILL_RELATIONS` and `validate_seed` are not defined.

- [ ] **Step 7: Add the exact curated relations and validator**

Append to `agent_hub/skill_graph/seed.py`:

```python
SUPPORTED_RELATIONS = {"REQUIRES", "RELATED_TO"}

SKILL_RELATIONS = [
    {"from": "Next.js", "type": "REQUIRES", "to": "React"},
    {"from": "React Native", "type": "REQUIRES", "to": "React"},
    {"from": "Kubernetes", "type": "REQUIRES", "to": "Docker"},
    {"from": "Kubernetes", "type": "REQUIRES", "to": "Linux"},
    {"from": "TensorFlow", "type": "REQUIRES", "to": "Python"},
    {"from": "PyTorch", "type": "REQUIRES", "to": "Python"},
    {"from": "Pandas", "type": "REQUIRES", "to": "Python"},
    {"from": "Scikit-learn", "type": "REQUIRES", "to": "Python"},
    {"from": "Spark", "type": "REQUIRES", "to": "SQL"},
    {"from": "React", "type": "RELATED_TO", "to": "Vue"},
    {"from": "React", "type": "RELATED_TO", "to": "Angular"},
    {"from": "TypeScript", "type": "RELATED_TO", "to": "JavaScript"},
    {"from": "Node.js", "type": "RELATED_TO", "to": "JavaScript"},
    {"from": "PostgreSQL", "type": "RELATED_TO", "to": "MySQL"},
    {"from": "MongoDB", "type": "RELATED_TO", "to": "Elasticsearch"},
    {"from": "AWS", "type": "RELATED_TO", "to": "Terraform"},
    {"from": "GCP", "type": "RELATED_TO", "to": "Terraform"},
    {"from": "Azure", "type": "RELATED_TO", "to": "Terraform"},
    {"from": "Swift", "type": "RELATED_TO", "to": "iOS"},
    {"from": "Kotlin", "type": "RELATED_TO", "to": "Android"},
    {"from": "TensorFlow", "type": "RELATED_TO", "to": "PyTorch"},
    {"from": "Pandas", "type": "RELATED_TO", "to": "NumPy"},
]


def validate_seed(categories: dict, relations: list[dict[str, str]]) -> None:
    canonical = {skill for data in categories.values() for skill in data["skills"]}
    alias_owner: dict[str, str] = {}
    for data in categories.values():
        for owner, aliases in data.get("aliases", {}).items():
            for alias in aliases:
                previous = alias_owner.setdefault(alias.casefold(), owner)
                if previous != owner:
                    raise ValueError(f"duplicate alias: {alias}")

    seen: set[tuple[str, str, str]] = set()
    requires: dict[str, set[str]] = {}
    for relation in relations:
        source, kind, target = relation["from"], relation["type"], relation["to"]
        for endpoint in (source, target):
            if endpoint not in canonical:
                raise ValueError(f"unknown relation endpoint: {endpoint}")
        if kind not in SUPPORTED_RELATIONS:
            raise ValueError(f"unsupported relation type: {kind}")
        if source == target:
            raise ValueError(f"self relation: {source}")
        key = (source, kind, target)
        if key in seen:
            raise ValueError(f"duplicate relation: {key}")
        seen.add(key)
        if kind == "REQUIRES":
            requires.setdefault(source, set()).add(target)

    def visit(node: str, active: set[str], complete: set[str]) -> None:
        if node in active:
            raise ValueError(f"REQUIRES cycle: {node}")
        if node in complete:
            return
        active.add(node)
        for target in requires.get(node, set()):
            visit(target, active, complete)
        active.remove(node)
        complete.add(node)

    complete: set[str] = set()
    for node in requires:
        visit(node, set(), complete)


validate_seed(SKILL_GRAPH_SEED, SKILL_RELATIONS)
```

Export `ExpansionEvidence` and `ExpansionResult` from `agent_hub/skill_graph/__init__.py`.

- [ ] **Step 8: Run Task 1 verification**

Run: `.venv/bin/python -m pytest tests/test_skill_graph_types.py tests/test_skill_graph_seed.py tests/test_skill_graph.py --collect-only -q && .venv/bin/ruff check agent_hub/skill_graph tests/test_skill_graph_types.py tests/test_skill_graph_seed.py`

Expected: new 7 tests PASS when run normally; existing Neo4j tests collect; Ruff exits 0.

- [ ] **Step 9: Commit Task 1**

```bash
git add agent_hub/skill_graph tests/test_skill_graph_types.py tests/test_skill_graph_seed.py
git commit -m "feat: add typed skill graph evidence and relations"
```

---

### Task 2: Implement Bounded Neo4j Evidence Expansion

**Files:**
- Modify: `agent_hub/skill_graph/service.py`
- Modify: `tests/test_skill_graph.py`

**Interfaces:**
- Consumes: `ExpansionEvidence`, `ExpansionResult`, `SKILL_RELATIONS` from Task 1.
- Produces: `SkillGraphService.expand_with_evidence(names, max_depth=2) -> ExpansionResult`.
- Preserves: `SkillGraphService.expand(names) -> set[str]`.

- [ ] **Step 1: Add failing integration cases**

Add these methods to `SkillGraphServiceTest` in `tests/test_skill_graph.py`:

```python
def test_expand_with_evidence_rejects_invalid_depth(self):
    with self.assertRaisesRegex(ValueError, "max_depth must be 1 or 2"):
        self.service.expand_with_evidence(["React"], max_depth=3)

def test_requires_is_directional(self):
    forward = self.service.expand_with_evidence(["Kubernetes"], max_depth=1)
    reverse = self.service.expand_with_evidence(["Docker"], max_depth=1)
    self.assertTrue(any(x.target == "Docker" and x.relations == ("REQUIRES",) for x in forward.evidence))
    self.assertFalse(any(x.target == "Kubernetes" and "REQUIRES" in x.relations for x in reverse.evidence))

def test_related_to_is_symmetric(self):
    react = self.service.expand_with_evidence(["React"], max_depth=1)
    vue = self.service.expand_with_evidence(["Vue"], max_depth=1)
    self.assertTrue(any(x.target == "Vue" and x.weight == 0.4 for x in react.evidence))
    self.assertTrue(any(x.target == "React" and x.weight == 0.4 for x in vue.evidence))

def test_two_hop_weight_and_cycle_protection(self):
    result = self.service.expand_with_evidence(["Next.js"], max_depth=2)
    vue_paths = [x for x in result.evidence if x.target == "Vue" and x.depth == 2]
    self.assertEqual(len(vue_paths), 1)
    self.assertEqual(vue_paths[0].weight, 0.2)
    self.assertEqual(len(vue_paths[0].nodes), len(set(vue_paths[0].nodes)))
```

- [ ] **Step 2: Run the focused class and verify RED**

Run: `.venv/bin/python -m pytest tests/test_skill_graph.py::SkillGraphServiceTest -v`

Expected: FAIL because `expand_with_evidence` does not exist and relation edges are not seeded.

- [ ] **Step 3: Seed `REQUIRES` and `RELATED_TO` edges**

In `SkillGraphService.seed()`, after canonical nodes exist, add:

```python
for relation in SKILL_RELATIONS:
    relation_type = relation["type"]
    if relation_type == "REQUIRES":
        query = (
            "MATCH (a:Skill {name: $source}), (b:Skill {name: $target}) "
            "MERGE (a)-[:REQUIRES]->(b)"
        )
    else:
        query = (
            "MATCH (a:Skill {name: $source}), (b:Skill {name: $target}) "
            "MERGE (a)-[:RELATED_TO]->(b)"
        )
    session.run(query, source=relation["from"], target=relation["to"])
```

- [ ] **Step 4: Implement bounded evidence expansion**

Add weight constants and `expand_with_evidence`. Use three one-hop queries and bounded two-hop
queries rather than an unrestricted variable-length traversal. Every returned row must include
`input`, `canonical`, `target`, `target_kind`, `relations`, and `nodes`.

```python
EDGE_WEIGHTS = {"REQUIRES": 0.75, "CHILD_OF": 0.65, "RELATED_TO": 0.40}

def _path_weight(relations: tuple[str, ...]) -> float:
    base = min(EDGE_WEIGHTS[name] for name in relations)
    return round(base * (0.5 if len(relations) == 2 else 1.0), 4)

def expand_with_evidence(self, names: list[str], *, max_depth: int = 2) -> ExpansionResult:
    if max_depth not in (1, 2):
        raise ValueError("max_depth must be 1 or 2")
    if not names:
        return ExpansionResult()

    rows: list[dict] = []
    with self.driver.session() as session:
        # Canonical/alias rows. Alias normalization has depth zero and weight one.
        rows.extend(session.run(
            "UNWIND $names AS input "
            "MATCH (raw {name: input}) WHERE raw:Skill OR raw:Category "
            "OPTIONAL MATCH (raw:Skill)-[:ALIAS_OF]->(canonical:Skill) "
            "WITH input, coalesce(canonical, raw) AS start "
            "RETURN input, start.name AS canonical, start.name AS target, "
            "CASE WHEN start:Category THEN 'category' ELSE 'skill' END AS target_kind, "
            "[] AS relations, [start.name] AS nodes",
            names=names,
        ).data())
        # Execute explicit CHILD_OF, outgoing REQUIRES, and undirected RELATED_TO queries.
        for query in self._evidence_queries(max_depth):
            rows.extend(session.run(query, names=names).data())

    evidence = []
    seen = set()
    for row in rows:
        relations = tuple(row["relations"])
        nodes = tuple(row["nodes"])
        if len(nodes) != len(set(nodes)):
            continue
        key = (row["input"], row["target"], relations, nodes)
        if key in seen:
            continue
        seen.add(key)
        evidence.append(ExpansionEvidence(
            input_skill=row["input"],
            canonical_skill=row["canonical"],
            target=row["target"],
            target_kind=row["target_kind"],
            relations=relations,
            nodes=nodes,
            depth=len(relations),
            weight=1.0 if not relations else _path_weight(relations),
        ))
    return ExpansionResult.from_iterable(evidence)
```

Implement `_evidence_queries(max_depth)` from an explicit query matrix. The shared prefix resolves
aliases before traversal, so alias normalization consumes no edge:

```python
_START = (
    "UNWIND $names AS input "
    "MATCH (raw:Skill {name: input}) "
    "OPTIONAL MATCH (raw)-[:ALIAS_OF]->(alias_target:Skill) "
    "WITH input, coalesce(alias_target, raw) AS start "
)
_RETURN = (
    "RETURN input, start.name AS canonical, target.name AS target, "
    "CASE WHEN target:Category THEN 'category' ELSE 'skill' END AS target_kind, "
    "relations, nodes"
)

_ONE_HOP = (
    _START
    + "MATCH (start)-[:CHILD_OF]->(target:Category) "
    + "WITH input, start, target, ['CHILD_OF'] AS relations, "
    + "[start.name, target.name] AS nodes "
    + _RETURN,
    _START
    + "MATCH (start)-[:REQUIRES]->(target:Skill) "
    + "WITH input, start, target, ['REQUIRES'] AS relations, "
    + "[start.name, target.name] AS nodes "
    + _RETURN,
    _START
    + "MATCH (start)-[:RELATED_TO]-(target:Skill) "
    + "WITH input, start, target, ['RELATED_TO'] AS relations, "
    + "[start.name, target.name] AS nodes "
    + _RETURN,
)

_TWO_HOP_BODIES = (
    "MATCH (start)-[:REQUIRES]->(middle:Skill)-[:REQUIRES]->(target:Skill) "
    "WITH input, start, middle, target, ['REQUIRES', 'REQUIRES'] AS relations",
    "MATCH (start)-[:REQUIRES]->(middle:Skill)-[:RELATED_TO]-(target:Skill) "
    "WITH input, start, middle, target, ['REQUIRES', 'RELATED_TO'] AS relations",
    "MATCH (start)-[:REQUIRES]->(middle:Skill)-[:CHILD_OF]->(target:Category) "
    "WITH input, start, middle, target, ['REQUIRES', 'CHILD_OF'] AS relations",
    "MATCH (start)-[:RELATED_TO]-(middle:Skill)-[:REQUIRES]->(target:Skill) "
    "WITH input, start, middle, target, ['RELATED_TO', 'REQUIRES'] AS relations",
    "MATCH (start)-[:RELATED_TO]-(middle:Skill)-[:RELATED_TO]-(target:Skill) "
    "WITH input, start, middle, target, ['RELATED_TO', 'RELATED_TO'] AS relations",
    "MATCH (start)-[:RELATED_TO]-(middle:Skill)-[:CHILD_OF]->(target:Category) "
    "WITH input, start, middle, target, ['RELATED_TO', 'CHILD_OF'] AS relations",
)


def _evidence_queries(max_depth: int) -> tuple[str, ...]:
    if max_depth == 1:
        return _ONE_HOP
    two_hop = tuple(
        _START
        + body
        + " WHERE start <> middle AND start <> target AND middle <> target "
        + "WITH input, start, target, relations, [start.name, middle.name, target.name] AS nodes "
        + _RETURN
        for body in _TWO_HOP_BODIES
    )
    return _ONE_HOP + two_hop
```

Keep `REQUIRES` directed, `RELATED_TO` undirected, and `CHILD_OF` terminal. Do not add a
`CHILD_OF`-first two-hop query; that would allow two concrete skills to match merely because they
share a category.

Update `expand()`:

```python
def expand(self, names: list[str]) -> set[str]:
    return self.expand_with_evidence(names, max_depth=1).targets()
```

- [ ] **Step 5: Run Task 2 verification**

Run: `.venv/bin/python -m pytest tests/test_skill_graph.py::SkillGraphServiceTest -v`

Expected: all service tests PASS when the Neo4j image is available. If the image cannot be
downloaded, record the Docker error and run `--collect-only`; do not report integration PASS.

Run: `.venv/bin/ruff check agent_hub/skill_graph tests/test_skill_graph.py && .venv/bin/ruff format --check agent_hub/skill_graph tests/test_skill_graph.py`

Expected: both commands exit 0.

- [ ] **Step 6: Commit Task 2**

```bash
git add agent_hub/skill_graph/service.py tests/test_skill_graph.py
git commit -m "feat: add bounded weighted skill graph traversal"
```

---

### Task 3: Add Deterministic Weighted Domain Scoring

**Files:**
- Modify: `agent_hub/agents/global_part_time/domain.py`
- Modify: `tests/test_domain.py`

**Interfaces:**
- Consumes: `Callable[[list[str]], ExpansionResult]` from Task 2.
- Produces: `score_match_with_evidence(...) -> tuple[float, dict[str, float], list[str], dict]`.
- Preserves: the existing three-value `score_match(...)` result.

- [ ] **Step 1: Write failing scoring tests**

Add a helper and focused tests to `tests/test_domain.py`:

```python
from agent_hub.skill_graph.types import ExpansionEvidence, ExpansionResult

def evidence(source, target, relations, nodes, weight, target_kind="skill", canonical=None):
    return ExpansionEvidence(
        source,
        canonical or source,
        target,
        target_kind,
        tuple(relations),
        tuple(nodes),
        len(relations),
        weight,
    )

class WeightedSkillEvidenceTest(unittest.TestCase):
    def test_direct_and_alias_match_score_one(self):
        # K8s canonicalizes to Kubernetes on the required side.
        def expand(names):
            values = []
            for name in names:
                canonical = "Kubernetes" if name == "K8s" else name
                values.append(evidence(name, canonical, [], [canonical], 1.0, canonical=canonical))
            return ExpansionResult.from_iterable(values)
        _, breakdown, _, graph = score_match_with_evidence(
            {"skills": [{"name": "Kubernetes"}]}, {"skills": ["K8s"]}, expand
        )
        self.assertEqual(breakdown["skills"], 1.0)
        self.assertEqual(graph["requirements"][0]["score"], 1.0)

    def test_requires_direction_and_weight(self):
        # Only job-side Kubernetes expansion reaches candidate-owned Docker.
        def expand(names):
            values = [evidence(name, name, [], [name], 1.0) for name in names]
            if names == ["Kubernetes"]:
                values.append(evidence("Kubernetes", "Docker", ["REQUIRES"], ["Kubernetes", "Docker"], 0.75))
            return ExpansionResult.from_iterable(values)
        _, breakdown, _, graph = score_match_with_evidence(
            {"skills": [{"name": "Docker"}]}, {"skills": ["Kubernetes"]}, expand
        )
        self.assertEqual(breakdown["skills"], 0.75)
        self.assertEqual(graph["requirements"][0]["path"]["relations"], ["REQUIRES"])

    def test_related_and_two_hop_weights(self):
        cases = [
            (
                "one hop",
                evidence("React", "Vue", ["RELATED_TO"], ["React", "Vue"], 0.4),
                0.4,
            ),
            (
                "two hops",
                evidence(
                    "Next.js",
                    "Vue",
                    ["REQUIRES", "RELATED_TO"],
                    ["Next.js", "React", "Vue"],
                    0.2,
                ),
                0.2,
            ),
        ]
        for label, path, expected in cases:
            with self.subTest(label=label):
                def expand(names):
                    values = [evidence(name, name, [], [name], 1.0) for name in names]
                    if names == [path.input_skill]:
                        values.append(path)
                    return ExpansionResult.from_iterable(values)

                _, breakdown, _, graph = score_match_with_evidence(
                    {"skills": [{"name": "Vue"}]},
                    {"skills": [path.input_skill]},
                    expand,
                )
                self.assertEqual(breakdown["skills"], expected)
                self.assertEqual(graph["requirements"][0]["score"], expected)

    def test_shared_category_does_not_match_two_concrete_skills(self):
        def expand(names):
            values = [evidence(name, name, [], [name], 1.0) for name in names]
            for name in names:
                if name in {"React", "Vue"}:
                    values.append(
                        evidence(
                            name,
                            "前端开发",
                            ["CHILD_OF"],
                            [name, "前端开发"],
                            0.65,
                            target_kind="category",
                        )
                    )
            return ExpansionResult.from_iterable(values)

        _, breakdown, _, graph = score_match_with_evidence(
            {"skills": [{"name": "React"}]}, {"skills": ["Vue"]}, expand
        )
        self.assertEqual(breakdown["skills"], 0.0)
        self.assertIsNone(graph["requirements"][0]["path"])

    def test_tie_break_uses_weight_depth_then_lexical_path(self):
        def expand(names):
            values = [evidence(name, name, [], [name], 1.0) for name in names]
            if names == ["Framework"]:
                values.extend([
                    evidence(
                        "Framework",
                        "React",
                        ["RELATED_TO", "RELATED_TO"],
                        ["Framework", "Angular", "React"],
                        0.2,
                    ),
                    evidence(
                        "Framework",
                        "React",
                        ["RELATED_TO", "RELATED_TO"],
                        ["Framework", "Vue", "React"],
                        0.2,
                    ),
                ])
            return ExpansionResult.from_iterable(values)

        _, _, _, graph = score_match_with_evidence(
            {"skills": [{"name": "React"}]}, {"skills": ["Framework"]}, expand
        )
        self.assertEqual(
            graph["requirements"][0]["path"]["nodes"],
            ["Framework", "Angular", "React"],
        )
```

- [ ] **Step 2: Run focused tests and verify RED**

Run: `.venv/bin/python -m pytest tests/test_domain.py::WeightedSkillEvidenceTest -v`

Expected: FAIL because `score_match_with_evidence` does not exist.

- [ ] **Step 3: Implement path selection and rich scoring**

In `domain.py`, define:

```python
ExpandEvidenceFn = Callable[[list[str]], ExpansionResult]

def _best_path(paths: list[ExpansionEvidence]) -> ExpansionEvidence | None:
    if not paths:
        return None
    return min(paths, key=lambda item: (-item.weight, item.depth, item.nodes, item.relations))

def score_match_with_evidence(
    candidate: dict[str, Any],
    job: dict[str, Any],
    expand_evidence_fn: ExpandEvidenceFn | None = None,
) -> tuple[float, dict[str, float], list[str], dict[str, Any]]:
    """Return the normal match result plus deterministic skill-graph evidence."""
```

The function must:

```python
owned_raw = [item["name"] if isinstance(item, dict) else item for item in candidate.get("skills") or []]
required_raw = list(job.get("skills") or [])
candidate_expansion = expand_evidence_fn(owned_raw) if expand_evidence_fn else ExpansionResult()
required_expansions = {
    required: expand_evidence_fn([required]) if expand_evidence_fn else ExpansionResult()
    for required in required_raw
}
```

For every required skill, build candidates in this order:

1. canonical equality from depth-zero evidence, score `1.0`;
2. candidate `CHILD_OF` evidence only when its target equals the required category;
3. required-side paths beginning with `REQUIRES` whose target equals an owned canonical skill;
4. candidate- or required-side `RELATED_TO` paths connecting the two canonical skills;
5. directionally valid two-hop variants of rules 2–4.

Choose `_best_path`, append one JSON requirement record, average requirement scores, and reuse
the existing non-skill breakdown calculation. Generate one deterministic reason per winning path.

Refactor the existing `score_match()` into a wrapper:

```python
def score_match(candidate, job, expand_fn=None):
    if expand_fn is None:
        total, breakdown, reasons, _ = score_match_with_evidence(candidate, job)
        return total, breakdown, reasons
    # Compatibility adapter: old set expansion remains weighted at 0.6.
    return _legacy_score_match(candidate, job, expand_fn)
```

Do not change callers using the legacy set callback in this task. Task 4 switches the application
path to the rich callback.

- [ ] **Step 4: Run Task 3 tests**

Run: `.venv/bin/python -m pytest tests/test_domain.py -v`

Expected: all existing and new domain tests PASS.

Run: `.venv/bin/ruff check agent_hub/agents/global_part_time/domain.py tests/test_domain.py && .venv/bin/ruff format --check agent_hub/agents/global_part_time/domain.py tests/test_domain.py`

Expected: both commands exit 0.

- [ ] **Step 5: Commit Task 3**

```bash
git add agent_hub/agents/global_part_time/domain.py tests/test_domain.py
git commit -m "feat: add weighted explainable skill scoring"
```

---

### Task 4: Persist Evidence With Whole-Batch Fallback

**Files:**
- Modify: `agent_hub/agents/global_part_time/service.py`
- Modify: `agent_hub/app.py`
- Modify: `tests/test_service.py`
- Modify: `tests/test_app_skill_graph_lifecycle.py`

**Interfaces:**
- `AgentService(..., expand_evidence_fn: Callable[[list[str]], ExpansionResult] | None = None)`.
- Match payload adds `skill_graph_evidence` with `mode`, `max_depth`, and `requirements`.

- [ ] **Step 1: Write failing service persistence and fallback tests**

Add to `tests/test_service.py`:

```python
def test_match_persists_only_winning_graph_evidence(self):
    self.service.review_source(self.source["id"], True, "operator")
    graph_job = dict(self.job, skills=["Kubernetes"])
    self.service.sync_source(self.source["id"], [graph_job], "worker")
    candidate = self.candidate()
    candidate["skills"] = [{"name": "Docker", "level": 4}]
    self.repo.put("candidate", candidate)

    def expand(names):
        values = [
            ExpansionEvidence(name, name, name, "skill", (), (name,), 0, 1.0)
            for name in names
        ]
        if names == ["Kubernetes"]:
            values.append(
                ExpansionEvidence(
                    "Kubernetes",
                    "Kubernetes",
                    "Docker",
                    "skill",
                    ("REQUIRES",),
                    ("Kubernetes", "Docker"),
                    1,
                    0.75,
                )
            )
        return ExpansionResult.from_iterable(values)

    self.service.expand_evidence_fn = expand
    match = self.service.run_matches(candidate["id"], "scheduler")["matches"][0]
    stored = self.repo.get("match", match["id"])
    self.assertEqual(match["skill_graph_evidence"]["mode"], "graph")
    self.assertEqual(match["skill_graph_evidence"]["requirements"][0]["score"], 0.75)
    self.assertNotIn("exception", match["skill_graph_evidence"])
    self.assertEqual(stored["skill_graph_evidence"], match["skill_graph_evidence"])

def test_no_graph_uses_direct_mode(self):
    self.service.review_source(self.source["id"], True, "operator")
    self.service.sync_source(self.source["id"], [self.job], "worker")
    candidate = self.candidate()
    result = self.service.run_matches(candidate["id"], "scheduler")
    self.assertEqual(result["matches"][0]["skill_graph_evidence"], {
        "mode": "direct", "max_depth": 0, "requirements": []
    })

def test_runtime_failure_recomputes_entire_batch_and_hides_exception_text(self):
    self.service.review_source(self.source["id"], True, "operator")
    jobs = [
        dict(
            self.job,
            source_job_id="frontend",
            canonical_url="https://feed.example.com/jobs/frontend",
            skills=["前端开发"],
        ),
        dict(
            self.job,
            source_job_id="backend",
            canonical_url="https://feed.example.com/jobs/backend",
            skills=["后端开发"],
        ),
    ]
    self.service.sync_source(self.source["id"], jobs, "worker")
    candidate = self.candidate()
    candidate["skills"] = [{"name": "React", "level": 4}]
    self.repo.put("candidate", candidate)

    def fail_on_backend(names):
        if names == ["后端开发"]:
            raise RuntimeError("secret bolt URI")
        return ExpansionResult.from_iterable(
            ExpansionEvidence(name, name, name, "skill", (), (name,), 0, 1.0)
            for name in names
        )

    self.service.expand_evidence_fn = fail_on_backend
    result = self.service.run_matches(candidate["id"], "scheduler")
    self.assertEqual(len(result["matches"]), 2)
    for match in self.repo.list("match"):
        self.assertEqual(match["skill_graph_evidence"]["mode"], "direct_fallback")
        self.assertEqual(match["skill_graph_evidence"]["requirements"], [])
        self.assertNotIn("secret bolt URI", repr(match))
```

Import `ExpansionEvidence` and `ExpansionResult` from `agent_hub.skill_graph.types` at the top of
the test file. Keep the existing `test_match_run_does_not_mask_scoring_failures`, updating its
patch target from `score_match` to `score_match_with_evidence` after the service switches callers.

- [ ] **Step 2: Run focused service tests and verify RED**

Run: `.venv/bin/python -m pytest tests/test_service.py -k 'graph_evidence or direct_mode or recomputes_entire_batch' -v`

Expected: FAIL because matches do not contain `skill_graph_evidence` and `AgentService` does not
accept the rich callback.

- [ ] **Step 3: Inject the rich callback and persist one consistent batch**

Update the constructor:

```python
def __init__(self, repository, expand_fn=None, expand_evidence_fn=None):
    self.repo = repository
    self.expand_fn = expand_fn
    self.expand_evidence_fn = expand_evidence_fn
```

In `run_matches`, retain hard filtering and the current in-memory batch boundary. Score all
eligible jobs with `score_match_with_evidence`. If the callback raises, discard all scored rows,
recompute every eligible job without a graph callback, and set fallback evidence before the first
`repo.put("match", ...)` call.

```python
mode = "graph" if self.expand_evidence_fn else "direct"
try:
    scored = [score_match_with_evidence(candidate, job, self.expand_evidence_fn) for job in eligible]
except Exception as exc:
    if self.expand_evidence_fn is None:
        raise
    logger.warning("Skill graph expansion failed; recomputing direct batch: %s", type(exc).__name__, exc_info=True)
    mode = "direct_fallback"
    scored = [score_match_with_evidence(candidate, job) for job in eligible]

for job, (score, breakdown, reasons, evidence) in zip(eligible, scored):
    evidence["mode"] = mode
    evidence["max_depth"] = 2 if mode == "graph" else 0
    match["skill_graph_evidence"] = evidence
    self.repo.put("match", match)
```

Catch only exceptions raised while invoking the external rich callback. Preserve the existing
test proving an unrelated patched `score_match_with_evidence` error propagates without writes.

In `app.py`, inject both compatibility and rich callbacks:

```python
part_time_service = AgentService(
    repo,
    expand_fn=skill_graph.expand if skill_graph else None,
    expand_evidence_fn=skill_graph.expand_with_evidence if skill_graph else None,
)
```

Keep the already implemented driver close behavior unchanged.

- [ ] **Step 4: Update lifecycle injection tests**

In `tests/test_app_skill_graph_lifecycle.py`, assert successful initialization assigns both bound
callbacks and seed failure assigns neither. Exit the `TestClient` context and retain the existing
single-close assertion.

- [ ] **Step 5: Run Task 4 verification**

Run: `.venv/bin/python -m pytest tests/test_service.py tests/test_app_skill_graph_lifecycle.py tests/test_domain.py -v`

Expected: all tests PASS; no partial or mixed graph/direct batch is persisted.

Run: `.venv/bin/ruff check agent_hub/app.py agent_hub/agents/global_part_time tests/test_service.py tests/test_app_skill_graph_lifecycle.py && .venv/bin/ruff format --check agent_hub/app.py agent_hub/agents/global_part_time tests/test_service.py tests/test_app_skill_graph_lifecycle.py`

Expected: both commands exit 0.

- [ ] **Step 6: Commit Task 4**

```bash
git add agent_hub/app.py agent_hub/agents/global_part_time/domain.py agent_hub/agents/global_part_time/service.py tests/test_service.py tests/test_app_skill_graph_lifecycle.py
git commit -m "feat: persist skill graph match evidence"
```

---

### Task 5: Add Local Neo4j Development Workflow

**Files:**
- Modify: `compose.dev.yaml`
- Modify: `.env.example`
- Modify: `Makefile`
- Modify: `docs/dev-guide.md`

**Interfaces:**
- Neo4j Browser: `http://127.0.0.1:7474`.
- Bolt: `bolt://127.0.0.1:7687`.
- Default local credentials: `neo4j` / `agent_hub_graph`.

- [ ] **Step 1: Add the Neo4j Compose service**

Add to `compose.dev.yaml`:

```yaml
  neo4j:
    image: neo4j:5
    environment:
      NEO4J_AUTH: ${NEO4J_USER:-neo4j}/${NEO4J_PASSWORD:-agent_hub_graph}
    ports:
      - "127.0.0.1:7474:7474"
      - "127.0.0.1:7687:7687"
    volumes:
      - neo4j_data:/data
    healthcheck:
      test: ["CMD-SHELL", "cypher-shell -u $${NEO4J_USER:-neo4j} -p $${NEO4J_PASSWORD:-agent_hub_graph} 'RETURN 1' || exit 1"]
      interval: 5s
      timeout: 5s
      retries: 20
```

Add `neo4j_data:` to the top-level `volumes` map.

- [ ] **Step 2: Add environment and Make targets**

Append to `.env.example`:

```dotenv
# --- Neo4j skill graph (optional) ---
# NEO4J_URI=bolt://127.0.0.1:7687
# NEO4J_USER=neo4j
# NEO4J_PASSWORD=agent_hub_graph
```

Add `test-neo4j` to `.PHONY` and add:

```make
test-neo4j: ## Neo4j skill graph integration tests (requires Docker image neo4j:5)
	. .venv/bin/activate && python -m pytest tests/test_skill_graph.py -v
```

Update `infra` and `infra-up` help text to say PostgreSQL, Redis, and Neo4j.

- [ ] **Step 3: Document the workflow**

Add a Neo4j section to `docs/dev-guide.md` with these exact commands:

```bash
docker compose -f compose.dev.yaml up -d neo4j --wait
docker compose -f compose.dev.yaml ps neo4j
NEO4J_URI=bolt://127.0.0.1:7687 uvicorn agent_hub.app:app --reload
make test-neo4j
```

Document that app startup seeds with `MERGE`, shutdown closes the driver, and absence/failure of
Neo4j activates deterministic direct matching.

- [ ] **Step 4: Validate configuration**

Run: `docker compose -f compose.dev.yaml config`

Expected: exit 0; Neo4j ports resolve only to `127.0.0.1`; `neo4j_data` is declared.

Run: `rg -n 'NEO4J_(URI|USER|PASSWORD)|test-neo4j|neo4j:5' .env.example Makefile compose.dev.yaml docs/dev-guide.md`

Expected: all four files contain the intended configuration or documentation.

- [ ] **Step 5: Commit Task 5**

```bash
git add compose.dev.yaml .env.example Makefile docs/dev-guide.md
git commit -m "docs: add Neo4j development workflow"
```

---

### Task 6: Complete End-to-End Verification

**Files:**
- Modify: `tests/test_skill_graph.py`
- Modify: `tests/test_service.py` only if an integration assertion needs the existing service fixture.

**Interfaces:**
- Verifies seed → traversal → deterministic scoring → match JSON evidence.

- [ ] **Step 1: Add the reverse alias and persisted evidence integration cases**

Add to `EndToEndSkillMatchTest`:

```python
def test_reverse_alias_direction_matches_with_real_graph(self):
    from agent_hub.agents.global_part_time.domain import score_match_with_evidence
    _, breakdown, _, evidence = score_match_with_evidence(
        {"skills": [{"name": "Kubernetes"}]},
        {"skills": ["K8s"]},
        self.service.expand_with_evidence,
    )
    self.assertEqual(breakdown["skills"], 1.0)
    self.assertEqual(evidence["requirements"][0]["score"], 1.0)

def test_real_graph_requires_path_is_explainable(self):
    from agent_hub.agents.global_part_time.domain import score_match_with_evidence
    _, breakdown, reasons, evidence = score_match_with_evidence(
        {"skills": [{"name": "Docker"}]},
        {"skills": ["Kubernetes"]},
        self.service.expand_with_evidence,
    )
    self.assertEqual(breakdown["skills"], 0.75)
    path = evidence["requirements"][0]["path"]
    self.assertEqual(path["relations"], ["REQUIRES"])
    self.assertEqual(path["nodes"], ["Kubernetes", "Docker"])
    self.assertTrue(any("Docker" in reason and "Kubernetes" in reason for reason in reasons))
```

- [ ] **Step 2: Run real Neo4j integration tests**

Run: `.venv/bin/python -m pytest tests/test_skill_graph.py -v`

Expected: all Neo4j tests PASS when Docker and `neo4j:5` are available. If image download fails,
capture the exact Docker error, run `--collect-only`, and report the external blocker separately.

- [ ] **Step 3: Run all non-Docker Python tests**

Run: `.venv/bin/python -m pytest tests/ -q --ignore=tests/test_skill_graph.py`

Expected: all collected non-Docker tests PASS; PostgreSQL tests may SKIP only when
`TEST_DATABASE_URL` is unset.

- [ ] **Step 4: Run quality checks**

Run: `.venv/bin/ruff check src tests && .venv/bin/ruff format --check agent_hub/skill_graph agent_hub/agents/global_part_time/domain.py agent_hub/agents/global_part_time/service.py agent_hub/app.py tests/test_skill_graph.py tests/test_skill_graph_types.py tests/test_skill_graph_seed.py tests/test_domain.py tests/test_service.py tests/test_app_skill_graph_lifecycle.py && git diff --check`

Expected: all commands exit 0.

- [ ] **Step 5: Run frontend regression verification**

Run from `frontend/`:

```bash
./node_modules/.bin/eslint . --ignore-pattern dist --ignore-pattern .next
WRANGLER_LOG_PATH=.wrangler/wrangler.log ./node_modules/.bin/vinext build
node --test tests/rendered-html.test.mjs
```

Expected: ESLint and build exit 0; all rendered HTML tests PASS.

- [ ] **Step 6: Commit Task 6**

```bash
git add tests/test_skill_graph.py tests/test_service.py
git commit -m "test: verify weighted skill graph matching"
```

If Task 6 produces no file changes after verification, do not create an empty commit; record the
verification evidence in the subagent progress ledger instead.
