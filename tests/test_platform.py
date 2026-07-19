import unittest
from typing import Any

from fastapi.testclient import TestClient

from agent_hub.app import create_app
from agent_hub.core.contracts import (
    ActionDefinition,
    ActionNotFoundError,
    AgentManifest,
    AuthorizationError,
    DuplicateAgentError,
    ExecutionContext,
    InvalidInvocationError,
)
from agent_hub.core.registry import AgentRegistry
from agent_hub.core.security import Principal, Role, SecuritySettings
from tests.inmemory_repo import InMemoryRepository


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
        self.context = ExecutionContext(
            principal=Principal(
                actor_id="tester",
                tenant_id="tenant-1",
                roles=frozenset({Role.USER}),
                trusted=True,
            ),
            request_id="request-1",
        )

    def test_catalog_and_invocation(self):
        self.assertEqual(self.registry.manifests()[0].agent_id, "example-agent")
        result = self.registry.invoke("example-agent", "read", {"value": 1}, self.context)
        self.assertEqual(result["actor"], "tester")
        self.assertEqual(self.context.tenant_id, "tenant-1")

    def test_only_declared_actions_can_run(self):
        with self.assertRaises(ActionNotFoundError):
            self.registry.invoke("example-agent", "__dict__", {}, self.context)

    def test_write_action_requires_idempotency_key(self):
        with self.assertRaises(InvalidInvocationError):
            self.registry.invoke("example-agent", "write", {}, self.context)

    def test_operator_only_action_rejects_user_principal(self):
        class OperatorAgent(ExampleAgent):
            def actions(self) -> tuple[ActionDefinition, ...]:
                return (
                    ActionDefinition(
                        "operate",
                        "Operator action",
                        allowed_roles=frozenset({Role.OPERATOR}),
                    ),
                )

        registry = AgentRegistry()
        registry.register(OperatorAgent())

        with self.assertRaises(AuthorizationError):
            registry.invoke("example-agent", "operate", {}, self.context)

    def test_operator_only_action_maps_user_denial_to_http_403(self):
        class OperatorAgent(ExampleAgent):
            def actions(self) -> tuple[ActionDefinition, ...]:
                return (
                    ActionDefinition(
                        "operate",
                        "Operator action",
                        allowed_roles=frozenset({Role.OPERATOR}),
                    ),
                )

        settings = SecuritySettings(
            mode="development",
            gateway_secret=None,
            development_default_roles=frozenset({Role.USER}),
        )
        client = TestClient(
            create_app(
                InMemoryRepository(":memory:"),
                extra_agents=(OperatorAgent(),),
                security_settings=settings,
            )
        )

        response = client.post(
            "/platform/v1/agents/example-agent/actions/operate",
            json={"payload": {}},
            headers={"X-Actor": "user-1"},
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            response.json(),
            {"detail": "action operate is not allowed for this principal"},
        )

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
