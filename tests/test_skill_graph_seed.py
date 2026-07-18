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
