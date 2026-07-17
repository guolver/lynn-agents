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
