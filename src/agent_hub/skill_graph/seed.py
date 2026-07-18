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
            "React",
            "Vue",
            "Angular",
            "TypeScript",
            "JavaScript",
            "HTML/CSS",
            "Next.js",
            "Tailwind CSS",
            "Svelte",
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
            "Python",
            "Java",
            "Go",
            "Node.js",
            "C#",
            "Ruby",
            "PHP",
            "Rust",
            "Scala",
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
            "PostgreSQL",
            "MySQL",
            "MongoDB",
            "Redis",
            "Elasticsearch",
            "SQLite",
            "Cassandra",
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
            "Docker",
            "Kubernetes",
            "AWS",
            "GCP",
            "Azure",
            "Terraform",
            "Linux",
        ],
        "aliases": {
            "Kubernetes": ["K8s", "k8s"],
            "AWS": ["Amazon Web Services", "aws"],
            "GCP": ["Google Cloud Platform", "Google Cloud", "gcp"],
            "Azure": ["azure", "Microsoft Azure"],
            "Terraform": ["terraform"],
            "Docker": ["docker"],
        },
    },
    "移动开发": {
        "skills": [
            "iOS",
            "Android",
            "React Native",
            "Flutter",
            "Swift",
            "Kotlin",
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
            "TensorFlow",
            "PyTorch",
            "Pandas",
            "Spark",
            "SQL",
            "Scikit-learn",
            "NumPy",
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
