"""Skill knowledge graph service backed by Neo4j."""

from __future__ import annotations

import neo4j

from .seed import SKILL_GRAPH_SEED, SKILL_RELATIONS
from .types import ExpansionEvidence, ExpansionResult


EDGE_WEIGHTS = {"REQUIRES": 0.75, "CHILD_OF": 0.65, "RELATED_TO": 0.40}

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


def _path_weight(relations: tuple[str, ...]) -> float:
    base = min(EDGE_WEIGHTS[name] for name in relations)
    return round(base * (0.5 if len(relations) == 2 else 1.0), 4)


def _evidence_queries(max_depth: int) -> tuple[str, ...]:
    if max_depth == 1:
        return _ONE_HOP
    two_hop = tuple(
        _START
        + body
        + " WHERE start <> middle AND start <> target AND middle <> target "
        + "WITH input, start, target, relations, "
        + "[start.name, middle.name, target.name] AS nodes "
        + _RETURN
        for body in _TWO_HOP_BODIES
    )
    return _ONE_HOP + two_hop


class SkillGraphService:
    """Provides alias resolution and bounded relation expansion over a Neo4j skill graph."""

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

    def resolve(self, name: str) -> str | None:
        """Resolve an alias to its canonical skill name.

        Returns the canonical name if ``name`` is an alias, ``name`` itself if
        it is already canonical, or ``None`` if the skill is unknown.
        """
        with self.driver.session() as session:
            result = session.run(
                "MATCH (s:Skill {name: $name}) "
                "OPTIONAL MATCH (s)-[:ALIAS_OF]->(canonical:Skill) "
                "RETURN coalesce(canonical.name, s.name) AS resolved",
                name=name,
            )
            record = result.single()
            if record is None:
                return None
            return record["resolved"]

    def expand(self, names: list[str]) -> set[str]:
        """Batch resolve aliases and return depth-one expansion targets.

        Returns a compatibility set containing canonical skill names, parent
        categories, requirements, and related skills. Unknown names are
        silently ignored.
        """
        return self.expand_with_evidence(names, max_depth=1).targets()

    def expand_with_evidence(self, names: list[str], *, max_depth: int = 2) -> ExpansionResult:
        """Expand skills through an explicit, bounded relation query matrix."""
        if max_depth not in (1, 2):
            raise ValueError("max_depth must be 1 or 2")
        if not names:
            return ExpansionResult()

        rows: list[dict] = []
        with self.driver.session() as session:
            rows.extend(
                session.run(
                    "UNWIND $names AS input "
                    "MATCH (raw {name: input}) WHERE raw:Skill OR raw:Category "
                    "OPTIONAL MATCH (raw:Skill)-[:ALIAS_OF]->(canonical:Skill) "
                    "WITH input, coalesce(canonical, raw) AS start "
                    "RETURN input, start.name AS canonical, start.name AS target, "
                    "CASE WHEN start:Category THEN 'category' ELSE 'skill' END AS target_kind, "
                    "[] AS relations, [start.name] AS nodes",
                    names=names,
                ).data()
            )
            for query in _evidence_queries(max_depth):
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
            evidence.append(
                ExpansionEvidence(
                    input_skill=row["input"],
                    canonical_skill=row["canonical"],
                    target=row["target"],
                    target_kind=row["target_kind"],
                    relations=relations,
                    nodes=nodes,
                    depth=len(relations),
                    weight=1.0 if not relations else _path_weight(relations),
                )
            )
        return ExpansionResult.from_iterable(evidence)

    def graph(self) -> dict:
        """Return the full skill graph as ``{nodes, links}`` for visualization."""
        nodes: list[dict] = []
        links: list[dict] = []
        with self.driver.session() as session:
            # Fetch all Category nodes
            for record in session.run("MATCH (c:Category) RETURN c.name AS name"):
                nodes.append({"id": record["name"], "type": "category"})

            # Fetch all Skill nodes with optional alias target
            for record in session.run(
                "MATCH (s:Skill) "
                "OPTIONAL MATCH (s)-[:ALIAS_OF]->(canonical:Skill) "
                "RETURN s.name AS name, canonical.name AS alias_of"
            ):
                node_type = "alias" if record["alias_of"] else "skill"
                nodes.append({"id": record["name"], "type": node_type})
                if record["alias_of"]:
                    links.append(
                        {
                            "source": record["name"],
                            "target": record["alias_of"],
                            "type": "ALIAS_OF",
                        }
                    )

            # Fetch CHILD_OF relationships
            for record in session.run(
                "MATCH (s:Skill)-[:CHILD_OF]->(c:Category) "
                "RETURN s.name AS skill, c.name AS category"
            ):
                links.append(
                    {
                        "source": record["skill"],
                        "target": record["category"],
                        "type": "CHILD_OF",
                    }
                )

        return {"nodes": nodes, "links": links}
