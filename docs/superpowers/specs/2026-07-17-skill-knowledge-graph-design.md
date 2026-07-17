# Skill Knowledge Graph Phase 2 Completion Design

## Status

Validated design for completing Phase 2 of the global part-time matching agent.

## Goal

Extend the existing Neo4j-backed alias and category graph into a bounded, weighted, and
explainable skill graph. Matching must remain deterministic, degrade safely when Neo4j is
unavailable, and persist only the graph evidence that affected each match score.

## Scope

This phase includes:

- Neo4j local development configuration in `compose.dev.yaml`.
- `ALIAS_OF`, `CHILD_OF`, `REQUIRES`, and `RELATED_TO` relationships.
- Weighted one-hop and two-hop traversal with cycle protection.
- Structured evidence paths for every graph-assisted skill match.
- Deterministic scoring and whole-batch fallback when graph expansion fails.
- Evidence stored in the existing match JSON payload.
- Unit, seed-validation, Testcontainers, and regression tests.

This phase does not include pgvector, embeddings, semantic retrieval, Celery workflows, or
normalizing evidence into the PostgreSQL `match_evidence` and `match_score_items` tables.
Those belong to later phases.

## Architecture

```text
candidate skills + job requirements
                |
                v
       SkillGraphService
       - resolve aliases
       - bounded traversal
       - return typed evidence
                |
                v
       deterministic domain scorer
       - apply direction rules
       - choose best path
       - calculate skill score
                |
                v
       AgentService.run_matches
       - score complete batch in memory
       - fall back as a complete batch
       - persist match + evidence
```

Neo4j owns graph nodes and relationships only. PostgreSQL and SQLite continue to own jobs,
candidates, matches, and audit records.

## Public Interfaces

`SkillGraphService.expand()` remains available for backward compatibility:

```python
def expand(self, names: list[str]) -> set[str]: ...
```

The new primary interface is:

```python
def expand_with_evidence(
    self,
    names: list[str],
    *,
    max_depth: int = 2,
) -> ExpansionResult: ...
```

`max_depth` accepts only `1` or `2`. Any other value raises `ValueError` before a database
query is executed.

`skill_graph/types.py` defines immutable result types. Each evidence item contains:

- `input_skill`: the caller-provided skill name.
- `canonical_skill`: the alias-resolved canonical name.
- `target`: the reached skill or category.
- `target_kind`: `skill` or `category`.
- `relations`: ordered relationship names in the selected path.
- `nodes`: ordered node names, including source and target.
- `depth`: relationship count after alias normalization.
- `weight`: calculated path weight.

The result supports stable JSON conversion for persistence and deterministic test assertions.

## Relationship Semantics

Base weights are fixed for this phase:

| Match path | Weight |
| --- | ---: |
| Direct canonical match | 1.00 |
| `ALIAS_OF` normalization | 1.00 |
| `REQUIRES` | 0.75 |
| `CHILD_OF` | 0.65 |
| `RELATED_TO` | 0.40 |

Direction rules are:

- Aliases are normalized on both candidate and job sides.
- `CHILD_OF` supports candidate concrete skill to job category matching.
- `REQUIRES` is traversed from a required job skill toward a prerequisite owned by the
  candidate. The reverse direction does not imply proficiency.
- `RELATED_TO` is treated as symmetric for matching, regardless of storage direction.
- Unknown skills do not expand.

For a two-hop path, the score is the lowest base edge weight in the path multiplied by `0.50`.
Alias normalization does not consume the traversal-depth budget. Paths may not repeat a node.

For each required job skill, the scorer selects one best candidate path. Paths are ordered by:

1. highest weight;
2. lowest depth;
3. lexicographically stable node and relationship sequence.

Only the winning path contributes to the score and persisted evidence. Multiple paths never
accumulate for the same requirement.

## Skill Score

Each job requirement receives a score between `0` and `1` from its best path. The final skill
score remains the arithmetic mean of all required-skill scores. A job with no skill requirements
retains the existing neutral score of `0.5`.

Direct and alias matches score `1.0`. Category, prerequisite, related, and two-hop matches use
their path weights. Two skills sharing a broad category do not automatically match each other;
the reached target must satisfy the job requirement under the direction rules above.

Recommendation reasons are generated from the winning evidence path, not from free-form model
output.

## Seed Data

`skill_graph/seed.py` keeps the existing six categories and aliases and adds a curated relation
list. Each relation has `from`, `type`, and `to` fields. Initial data uses this exact set:

- `REQUIRES`: Next.js→React, React Native→React, Kubernetes→Docker, Kubernetes→Linux,
  TensorFlow→Python, PyTorch→Python, Pandas→Python, Scikit-learn→Python, and Spark→SQL.
- `RELATED_TO`: React↔Vue, React↔Angular, TypeScript↔JavaScript, Node.js↔JavaScript,
  PostgreSQL↔MySQL, MongoDB↔Elasticsearch, AWS↔Terraform, GCP↔Terraform,
  Azure↔Terraform, Swift↔iOS, Kotlin↔Android, TensorFlow↔PyTorch, and Pandas↔NumPy.

`RELATED_TO` is stored once per pair and queried as an undirected relationship.

Pure validation rejects:

- aliases owned by more than one canonical skill;
- relationships whose endpoints are not canonical skills;
- unsupported relationship types;
- self-references;
- duplicate `(from, type, to)` relationships;
- directed `REQUIRES` cycles within the curated seed.

`seed()` uses Neo4j `MERGE`, so repeated execution is idempotent.

## Match Persistence

Each persisted match adds a `skill_graph_evidence` object:

```json
{
  "mode": "graph",
  "max_depth": 2,
  "requirements": [
    {
      "required_skill": "Kubernetes",
      "candidate_skill": "Docker",
      "score": 0.75,
      "path": {
        "input_skill": "Kubernetes",
        "canonical_skill": "Kubernetes",
        "target": "Docker",
        "relations": ["REQUIRES"],
        "nodes": ["Kubernetes", "Docker"],
        "depth": 1,
        "weight": 0.75
      }
    }
  ]
}
```

When graph expansion fails, the complete eligible job batch is recomputed without graph scores
before any match is persisted. Fallback evidence uses:

```json
{"mode": "direct_fallback", "requirements": []}
```

Logs record the exception class and operational context. Match JSON does not store exception
messages, connection strings, credentials, or stack traces.

Dedicated `match_evidence` and `match_score_items` rows are deferred to Phase 4 so SQLite and
PostgreSQL retain repository-contract parity in this phase.

## Failure Handling

- No `NEO4J_URI`: use direct matching and persist `mode: direct`.
- Initialization or seed failure: close the driver and start in direct mode.
- Runtime query failure: log once, discard all graph scores for that run, recompute the complete
  eligible batch in direct mode, and then persist.
- Non-graph scoring errors continue to propagate and leave no partially persisted batch.
- Application shutdown closes the Neo4j driver idempotently.

## Local Development

`compose.dev.yaml` adds `neo4j:5` with:

- loopback-only ports `127.0.0.1:7474:7474` and `127.0.0.1:7687:7687`;
- a named data volume;
- local-only credentials supplied through environment defaults;
- a `cypher-shell` health check.

`.env.example` documents `NEO4J_URI`, `NEO4J_USER`, and `NEO4J_PASSWORD`. Development docs
describe startup, health verification, seed behavior, and focused integration-test commands.

## Testing

Tests are divided into four groups:

1. Pure scoring tests for every weight, relationship direction, two-hop decay, tie-breaking,
   unknown skills, and prevention of shared-category false positives.
2. Seed validation tests for unique aliases, valid endpoints, supported types, self-links,
   duplicates, and `REQUIRES` cycles.
3. Service tests for stable JSON evidence, whole-batch fallback, no partial writes, and unchanged
   behavior without Neo4j.
4. Testcontainers tests for real Cypher paths, depth limits, cycle avoidance, symmetric
   `RELATED_TO`, directional `REQUIRES`, idempotent seed, and persisted match evidence.

Docker or image-download failures are reported as environmental blockers. They are not reported
as passing integration tests. All non-Docker suites must remain green.

## Delivery Order

1. Add result types and validated relation seed data.
2. Implement Neo4j evidence traversal and compatibility expansion.
3. Implement weighted domain scoring and persisted match evidence.
4. Add Compose, environment, and development documentation.
5. Run focused, full non-Docker, and real Neo4j integration verification.
