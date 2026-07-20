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
        later = ExpansionEvidence(
            "React", "React", "Vue", "skill", ("RELATED_TO",), ("React", "Vue"), 1, 0.4
        )
        earlier = ExpansionEvidence(
            "React", "React", "Angular", "skill", ("RELATED_TO",), ("React", "Angular"), 1, 0.4
        )
        result = ExpansionResult.from_iterable([later, earlier])
        self.assertEqual([item.target for item in result.evidence], ["Angular", "Vue"])
