"""JSON Schema validation tests for AgentRegistry."""

import unittest

from agent_hub.core.contracts import (
    ActionDefinition,
    InvalidInvocationError,
    Role,
)
from agent_hub.core.registry import AgentRegistry


class TestJsonSchemaValidation(unittest.TestCase):
    """Test JSON Schema validation in AgentRegistry._validate_payload."""

    def setUp(self) -> None:
        self.registry = AgentRegistry()

    def _make_action(self, input_schema: dict) -> ActionDefinition:
        """Helper to create an ActionDefinition with given schema."""
        return ActionDefinition(
            name="test_action",
            description="Test action",
            allowed_roles={Role.USER},
            input_schema=input_schema,
        )

    # --- Backward compatibility tests (required-only schemas) ---

    def test_required_only_schema_passes_with_all_fields(self) -> None:
        """Schemas with only 'required' should use fast path and pass."""
        action = self._make_action({"required": ["name", "age"]})
        payload = {"name": "Alice", "age": 30}
        # Should not raise
        self.registry._validate_payload(action, payload)

    def test_required_only_schema_fails_with_missing_fields(self) -> None:
        """Schemas with only 'required' should raise for missing fields."""
        action = self._make_action({"required": ["name", "age"]})
        payload = {"name": "Alice"}
        with self.assertRaises(InvalidInvocationError) as ctx:
            self.registry._validate_payload(action, payload)
        self.assertIn("missing required payload fields", str(ctx.exception))
        self.assertIn("age", str(ctx.exception))

    def test_required_only_schema_fails_with_null_value(self) -> None:
        """Null values should be treated as missing for required-only schemas."""
        action = self._make_action({"required": ["name"]})
        payload = {"name": None}
        with self.assertRaises(InvalidInvocationError) as ctx:
            self.registry._validate_payload(action, payload)
        self.assertIn("name", str(ctx.exception))

    def test_empty_schema_passes(self) -> None:
        """Empty schema should allow any payload."""
        action = self._make_action({})
        payload = {"anything": "goes"}
        # Should not raise
        self.registry._validate_payload(action, payload)

    # --- Full JSON Schema validation tests ---

    def test_type_validation_string(self) -> None:
        """String type validation should reject non-strings."""
        action = self._make_action(
            {
                "type": "object",
                "properties": {"name": {"type": "string"}},
            }
        )
        # Valid
        self.registry._validate_payload(action, {"name": "Alice"})

        # Invalid
        with self.assertRaises(InvalidInvocationError) as ctx:
            self.registry._validate_payload(action, {"name": 123})
        self.assertIn("payload validation failed", str(ctx.exception))
        self.assertIn("name", str(ctx.exception))

    def test_type_validation_integer(self) -> None:
        """Integer type validation should reject non-integers."""
        action = self._make_action(
            {
                "type": "object",
                "properties": {"count": {"type": "integer"}},
            }
        )
        # Valid
        self.registry._validate_payload(action, {"count": 42})

        # Invalid - string
        with self.assertRaises(InvalidInvocationError) as ctx:
            self.registry._validate_payload(action, {"count": "42"})
        self.assertIn("count", str(ctx.exception))

        # Invalid - float
        with self.assertRaises(InvalidInvocationError) as ctx:
            self.registry._validate_payload(action, {"count": 3.14})
        self.assertIn("count", str(ctx.exception))

    def test_type_validation_array(self) -> None:
        """Array type validation should reject non-arrays."""
        action = self._make_action(
            {
                "type": "object",
                "properties": {"tags": {"type": "array", "items": {"type": "string"}}},
            }
        )
        # Valid
        self.registry._validate_payload(action, {"tags": ["a", "b"]})

        # Invalid - not array
        with self.assertRaises(InvalidInvocationError) as ctx:
            self.registry._validate_payload(action, {"tags": "not-an-array"})
        self.assertIn("tags", str(ctx.exception))

    def test_required_with_full_schema(self) -> None:
        """Required fields with full schema should be validated."""
        action = self._make_action(
            {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "email": {"type": "string"},
                },
                "required": ["name", "email"],
            }
        )
        # Valid
        self.registry._validate_payload(action, {"name": "Alice", "email": "alice@example.com"})

        # Invalid - missing required
        with self.assertRaises(InvalidInvocationError) as ctx:
            self.registry._validate_payload(action, {"name": "Alice"})
        self.assertIn("payload validation failed", str(ctx.exception))
        self.assertIn("email", str(ctx.exception))

    def test_minimum_maximum_constraints(self) -> None:
        """Numeric constraints should be enforced."""
        action = self._make_action(
            {
                "type": "object",
                "properties": {"age": {"type": "integer", "minimum": 0, "maximum": 150}},
            }
        )
        # Valid
        self.registry._validate_payload(action, {"age": 25})

        # Invalid - too small
        with self.assertRaises(InvalidInvocationError) as ctx:
            self.registry._validate_payload(action, {"age": -1})
        self.assertIn("age", str(ctx.exception))

        # Invalid - too large
        with self.assertRaises(InvalidInvocationError) as ctx:
            self.registry._validate_payload(action, {"age": 200})
        self.assertIn("age", str(ctx.exception))

    def test_string_pattern_validation(self) -> None:
        """String pattern validation should enforce regex."""
        action = self._make_action(
            {
                "type": "object",
                "properties": {"email": {"type": "string", "pattern": r"^[^@]+@[^@]+\.[^@]+$"}},
            }
        )
        # Valid
        self.registry._validate_payload(action, {"email": "test@example.com"})

        # Invalid
        with self.assertRaises(InvalidInvocationError) as ctx:
            self.registry._validate_payload(action, {"email": "not-an-email"})
        self.assertIn("email", str(ctx.exception))

    def test_enum_validation(self) -> None:
        """Enum validation should restrict to allowed values."""
        action = self._make_action(
            {
                "type": "object",
                "properties": {
                    "status": {"type": "string", "enum": ["active", "inactive", "pending"]}
                },
            }
        )
        # Valid
        self.registry._validate_payload(action, {"status": "active"})

        # Invalid
        with self.assertRaises(InvalidInvocationError) as ctx:
            self.registry._validate_payload(action, {"status": "unknown"})
        self.assertIn("status", str(ctx.exception))

    def test_nested_object_validation(self) -> None:
        """Nested objects should be validated recursively."""
        action = self._make_action(
            {
                "type": "object",
                "properties": {
                    "user": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "age": {"type": "integer"},
                        },
                        "required": ["name"],
                    }
                },
            }
        )
        # Valid
        self.registry._validate_payload(action, {"user": {"name": "Alice", "age": 30}})

        # Invalid - missing nested required
        with self.assertRaises(InvalidInvocationError) as ctx:
            self.registry._validate_payload(action, {"user": {"age": 30}})
        self.assertIn("user", str(ctx.exception))
        self.assertIn("name", str(ctx.exception))

    def test_multiple_errors_collected(self) -> None:
        """Multiple validation errors should be collected and reported."""
        action = self._make_action(
            {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "age": {"type": "integer"},
                },
                "required": ["name", "age"],
            }
        )
        # Multiple errors
        with self.assertRaises(InvalidInvocationError) as ctx:
            self.registry._validate_payload(action, {})
        error_msg = str(ctx.exception)
        self.assertIn("payload validation failed", error_msg)
        # Both fields should be mentioned
        self.assertIn("name", error_msg)
        self.assertIn("age", error_msg)

    def test_additional_properties_allowed_by_default(self) -> None:
        """Additional properties should be allowed by default."""
        action = self._make_action(
            {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                },
            }
        )
        # Should pass - extra field allowed
        self.registry._validate_payload(action, {"name": "Alice", "extra": "ignored"})

    def test_additional_properties_forbidden(self) -> None:
        """additionalProperties: false should reject extra fields."""
        action = self._make_action(
            {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                },
                "additionalProperties": False,
            }
        )
        # Valid
        self.registry._validate_payload(action, {"name": "Alice"})

        # Invalid - extra property
        with self.assertRaises(InvalidInvocationError) as ctx:
            self.registry._validate_payload(action, {"name": "Alice", "extra": "not-allowed"})
        self.assertIn("payload validation failed", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
