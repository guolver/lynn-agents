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
