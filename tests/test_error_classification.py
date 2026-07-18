"""Unit tests for error classification — no infrastructure required."""

import unittest

from agent_hub.worker.errors import (
    CandidateUnsubscribedError,
    ClassifiedError,
    EmailServiceTemporaryError,
    HighRiskFlaggedError,
    InputSchemaError,
    PermanentError,
    RateLimitError,
    RetryableError,
    SourceTimeoutError,
    SourceUnauthorizedError,
    TransientDatabaseError,
    classify,
)


class TestClassify(unittest.TestCase):
    # ---- Retryable hierarchy ----

    def test_retryable_base(self):
        err = RetryableError("transient")
        result = classify(err)
        self.assertIsInstance(result, ClassifiedError)
        self.assertEqual(result.category, "retryable")
        self.assertEqual(result.error_class, "RetryableError")
        self.assertIs(result.original, err)

    def test_source_timeout(self):
        result = classify(SourceTimeoutError("timed out"))
        self.assertEqual(result.category, "retryable")
        self.assertEqual(result.error_class, "SourceTimeoutError")

    def test_rate_limit(self):
        result = classify(RateLimitError("429"))
        self.assertEqual(result.category, "retryable")
        self.assertEqual(result.error_class, "RateLimitError")

    def test_email_temporary(self):
        result = classify(EmailServiceTemporaryError("smtp fail"))
        self.assertEqual(result.category, "retryable")

    def test_transient_database(self):
        result = classify(TransientDatabaseError("deadlock"))
        self.assertEqual(result.category, "retryable")

    # ---- Permanent hierarchy ----

    def test_permanent_base(self):
        result = classify(PermanentError("bad"))
        self.assertEqual(result.category, "permanent")
        self.assertEqual(result.error_class, "PermanentError")

    def test_source_unauthorized(self):
        result = classify(SourceUnauthorizedError("401"))
        self.assertEqual(result.category, "permanent")

    def test_input_schema(self):
        result = classify(InputSchemaError("missing field"))
        self.assertEqual(result.category, "permanent")

    def test_candidate_unsubscribed(self):
        result = classify(CandidateUnsubscribedError("opted out"))
        self.assertEqual(result.category, "permanent")

    def test_high_risk_flagged(self):
        result = classify(HighRiskFlaggedError("flagged"))
        self.assertEqual(result.category, "permanent")

    # ---- Builtin types ----

    def test_connection_error_is_retryable(self):
        result = classify(ConnectionError("refused"))
        self.assertEqual(result.category, "retryable")
        self.assertEqual(result.error_class, "ConnectionError")

    def test_timeout_error_is_retryable(self):
        result = classify(TimeoutError("timed out"))
        self.assertEqual(result.category, "retryable")

    def test_os_error_is_retryable(self):
        result = classify(OSError("disk"))
        self.assertEqual(result.category, "retryable")

    def test_value_error_is_permanent(self):
        result = classify(ValueError("bad input"))
        self.assertEqual(result.category, "permanent")

    def test_type_error_is_permanent(self):
        result = classify(TypeError("wrong type"))
        self.assertEqual(result.category, "permanent")

    # ---- Domain errors ----

    def test_not_found_error_is_permanent(self):
        from agent_hub.agents.global_part_time.service import NotFoundError

        result = classify(NotFoundError("job 123 not found"))
        self.assertEqual(result.category, "permanent")
        self.assertEqual(result.error_class, "NotFoundError")

    def test_policy_error_is_permanent(self):
        from agent_hub.agents.global_part_time.service import PolicyError

        result = classify(PolicyError("not approved"))
        self.assertEqual(result.category, "permanent")

    # ---- Unknown defaults to retryable ----

    def test_unknown_exception_is_retryable(self):
        result = classify(RuntimeError("unexpected"))
        self.assertEqual(result.category, "retryable")
        self.assertEqual(result.error_class, "RuntimeError")

    def test_message_preserved(self):
        err = SourceTimeoutError("upstream took 30s")
        result = classify(err)
        self.assertEqual(result.message, "upstream took 30s")

    def test_classified_error_is_frozen(self):
        result = classify(RetryableError("x"))
        with self.assertRaises(AttributeError):
            result.category = "permanent"  # type: ignore[misc]


if __name__ == "__main__":
    unittest.main()
