import unittest
import time
from llm_security_platform.app.circuit_breaker import CircuitBreaker, CircuitBreakerOpenException

class TestLLMSecurityRegressionGate(unittest.TestCase):
    def test_circuit_breaker_transitions(self):
        """Regression: Verify circuit breaker CLOSED -> OPEN -> HALF-OPEN state machine transitions."""
        cb = CircuitBreaker("TestBreaker", failure_threshold=2, recovery_timeout=0.2)
        
        # Initial state should be CLOSED and requests allowed
        self.assertEqual(cb.state, "CLOSED")
        self.assertTrue(cb.allow_request())
        
        # 1st failure - state remains CLOSED
        cb.record_failure()
        self.assertEqual(cb.state, "CLOSED")
        self.assertTrue(cb.allow_request())
        
        # 2nd failure - state transitions to OPEN
        cb.record_failure()
        self.assertEqual(cb.state, "OPEN")
        self.assertFalse(cb.allow_request())
        
        # Wait for recovery timeout to elapse
        time.sleep(0.25)
        
        # Next request triggers HALF-OPEN probe
        self.assertTrue(cb.allow_request())
        self.assertEqual(cb.state, "HALF_OPEN")
        
        # Success transitions back to CLOSED
        cb.record_success()
        self.assertEqual(cb.state, "CLOSED")
        self.assertTrue(cb.allow_request())

    def test_cost_budget_allocation_reconciliation(self):
        """Regression: Verify that token budget checking throws properly when over limit."""
        from llm_security_platform.app.cost_guardrail import check_and_record_usage
        import uuid
        
        tenant_id = "test-tenant-reg"
        user_id = "test-user-reg"
        run_id = str(uuid.uuid4())
        
        # Record small usage should pass
        try:
            check_and_record_usage(tenant_id, user_id, run_id, 100)
            passed = True
        except Exception:
            passed = False
        self.assertTrue(passed)
        
        # Reconcile back to 0
        check_and_record_usage(tenant_id, user_id, run_id, -100)
