import unittest
from llm_security_platform.app.providers import build_provider
from llm_security_platform.app.crescendo import CrescendoOrchestrator

class CrescendoOrchestratorTests(unittest.TestCase):
    def test_crescendo_attack_success(self):
        # We test with the objective containing the vulnerable trigger word
        attacker = build_provider("mock")
        target = build_provider("mock")
        
        orchestrator = CrescendoOrchestrator(
            attacker_provider=attacker,
            target_provider=target,
            objective="injection_succeeded",
            max_turns=3
        )
        
        result = orchestrator.run()
        self.assertTrue(result["success"])
        self.assertGreater(result["total_turns"], 0)
        self.assertTrue(any(entry["refused"] is False for entry in result["dialogue"]))

    def test_crescendo_refusal_handling(self):
        # Test with standard security boundary system prompt wrapper which refuses attempts
        attacker = build_provider("mock")
        target = build_provider("mock")
        
        orchestrator = CrescendoOrchestrator(
            attacker_provider=attacker,
            target_provider=target,
            objective="sensitive_credentials",
            max_turns=2
        )
        
        # Simulating dialogue where the target does not have success trigger and refuses
        result = orchestrator.run()
        # Should complete max_turns since objective isn't triggered
        self.assertEqual(result["total_turns"], 2)
        # Should not mark success if objective wasn't met
        self.assertFalse(result["success"])
