import unittest
from typing import Any

from agent_hub.core.contracts import (
    ActionDefinition,
    ActionNotFoundError,
    AgentManifest,
    DuplicateAgentError,
    ExecutionContext,
    InvalidInvocationError,
)
from agent_hub.core.registry import AgentRegistry


class ExampleAgent:
    manifest = AgentManifest(
        agent_id="example-agent",
        name="Example",
        version="1.0.0",
        description="Test agent",
    )

    def actions(self) -> tuple[ActionDefinition, ...]:
        return (
            ActionDefinition("read", "Read data"),
            ActionDefinition(
                "write",
                "Write data",
                mode="write",
                requires_idempotency_key=True,
            ),
        )

    def invoke(
        self, action: str, payload: dict[str, Any], context: ExecutionContext
    ) -> dict[str, Any]:
        return {"action": action, "payload": payload, "actor": context.actor}


class AgentRegistryTest(unittest.TestCase):
    def setUp(self):
        self.registry = AgentRegistry()
        self.registry.register(ExampleAgent())
        self.context = ExecutionContext(actor="tester", request_id="request-1")

    def test_catalog_and_invocation(self):
        self.assertEqual(self.registry.manifests()[0].agent_id, "example-agent")
        result = self.registry.invoke("example-agent", "read", {"value": 1}, self.context)
        self.assertEqual(result["actor"], "tester")

    def test_only_declared_actions_can_run(self):
        with self.assertRaises(ActionNotFoundError):
            self.registry.invoke("example-agent", "__dict__", {}, self.context)

    def test_write_action_requires_idempotency_key(self):
        with self.assertRaises(InvalidInvocationError):
            self.registry.invoke("example-agent", "write", {}, self.context)

    def test_manifest_required_fields_are_checked_before_agent_runs(self):
        class RequiredInputAgent(ExampleAgent):
            def actions(self) -> tuple[ActionDefinition, ...]:
                return (
                    ActionDefinition(
                        "needs-input",
                        "Needs value",
                        input_schema={"required": ["value"]},
                    ),
                )

        registry = AgentRegistry()
        registry.register(RequiredInputAgent())
        with self.assertRaises(InvalidInvocationError):
            registry.invoke("example-agent", "needs-input", {}, self.context)

    def test_duplicate_registration_is_rejected(self):
        with self.assertRaises(DuplicateAgentError):
            self.registry.register(ExampleAgent())


if __name__ == "__main__":
    unittest.main()
