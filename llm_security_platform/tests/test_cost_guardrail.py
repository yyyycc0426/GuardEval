import unittest
from unittest.mock import patch

from llm_security_platform.app.cost_guardrail import (
    check_and_record_usage,
    BudgetExceededError,
    _in_memory_budgets
)

class CostGuardrailTests(unittest.TestCase):
    def setUp(self):
        # Clear in-memory budgets before each test
        _in_memory_budgets.clear()
        
        # Clear database budgets to prevent persistent test crosstalk
        from llm_security_platform.app.production_store import session_scope
        from llm_security_platform.app.production_models import TenantBudgetMeter
        from sqlalchemy import delete
        try:
            with session_scope() as session:
                session.execute(delete(TenantBudgetMeter))
        except Exception:
            pass

    @patch("llm_security_platform.app.cost_guardrail.get_redis")
    def test_under_budget_runs(self, mock_get_redis):
        # Redis is offline, fallbacks to local memory
        mock_get_redis.return_value = None
        
        # Checking with 0 tokens shouldn't raise exception
        try:
            check_and_record_usage("t1", "u1", "r1", 0)
        except BudgetExceededError as exc:
            self.fail(f"check_and_record_usage raised BudgetExceededError unexpectedly: {exc}")

        # Adding 1000 tokens should succeed
        check_and_record_usage("t1", "u1", "r1", 1000)

    @patch("llm_security_platform.app.cost_guardrail.get_redis")
    def test_run_budget_exceeded(self, mock_get_redis):
        mock_get_redis.return_value = None
        
        # Exceeding run budget of 50k
        with self.assertRaises(BudgetExceededError) as context:
            check_and_record_usage("t_run", "u_run", "r_run", 55000)
            
        self.assertEqual(context.exception.error_code, "RUN_BUDGET_EXCEEDED")

    @patch("llm_security_platform.app.cost_guardrail.get_redis")
    def test_user_daily_budget_exceeded(self, mock_get_redis):
        mock_get_redis.return_value = None
        
        # User budget is 200k, we execute 5 runs of 45k each under the same user (using unique tenant 't_user')
        for i in range(4):
            check_and_record_usage("t_user", "u_user", f"r_user_{i}", 45000)
            
        # The 5th run of 45k should exceed user daily limit (45k * 5 = 225k > 200k)
        with self.assertRaises(BudgetExceededError) as context:
            check_and_record_usage("t_user", "u_user", "r_user_5", 45000)
            
        self.assertEqual(context.exception.error_code, "USER_BUDGET_EXCEEDED")

    @patch("llm_security_platform.app.cost_guardrail.get_redis")
    def test_tenant_daily_budget_exceeded(self, mock_get_redis):
        mock_get_redis.return_value = None
        
        # Tenant budget is 1M. We simulate 22 users doing 45k tokens each (990k total)
        for i in range(22):
            check_and_record_usage("t_tenant", f"u_tenant_{i}", f"r_tenant_{i}", 45000)
            
        # The 23rd call of 45k should exceed tenant daily limit (990k + 45k = 1.035M > 1M)
        with self.assertRaises(BudgetExceededError) as context:
            check_and_record_usage("t_tenant", "u_tenant_last", "r_tenant_last", 45000)
            
        self.assertEqual(context.exception.error_code, "TENANT_BUDGET_EXCEEDED")

    @patch("llm_security_platform.app.cost_guardrail.get_redis")
    @patch("llm_security_platform.app.cost_guardrail._load_initial_from_db")
    def test_budget_initial_load_from_db(self, mock_load_db, mock_get_redis):
        mock_get_redis.return_value = None
        # DB returns 5000 for tenant, 3000 for user
        mock_load_db.return_value = (5000, 3000)
        
        # Checking with 0 tokens. This triggers _get_or_load_budgets
        check_and_record_usage("t_db", "u_db", "r_db", 0)
        
        # Verify db loader was called
        mock_load_db.assert_called_once()
        
        # Verifies it recovered 5000 and 3000.
        # User budget is 200k. Current user budget is 3000.
        # To exceed 200k, we need 197001 more.
        # But we must not exceed the run budget of 50000 in a single call.
        # So we make 4 calls of 45000, and 1 call of 20000.
        for i in range(4):
            check_and_record_usage("t_db", "u_db", f"r_db_call_{i}", 45000)
            
        with self.assertRaises(BudgetExceededError) as context:
            check_and_record_usage("t_db", "u_db", "r_db_call_last", 20000)
            
        self.assertEqual(context.exception.error_code, "USER_BUDGET_EXCEEDED")
