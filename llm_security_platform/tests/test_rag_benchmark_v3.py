import unittest
from pathlib import Path

from llm_security_platform.app.dataset import load_dataset, validate_dataset
from llm_security_platform.app.rag_context import retrieved_documents_for_case
from llm_security_platform.policies.base import DefenseContext
from llm_security_platform.policies.policy_engine import PolicyEngine


DATASET = Path(__file__).resolve().parents[1] / "data" / "attack_cases_v3.json"


class RagBenchmarkV3Tests(unittest.TestCase):
    def test_rag_canary_is_only_in_retrieved_documents(self):
        cases = load_dataset(DATASET)
        self.assertEqual(validate_dataset(cases), [])
        rag_cases = [case for case in cases if case["risk_type"] == "rag_data_leakage"]
        self.assertEqual(len(rag_cases), 6)
        for case in rag_cases:
            self.assertNotIn("rag_canary_fin_7391", case["prompt"].lower())
            documents = retrieved_documents_for_case(case)
            self.assertTrue(documents)
            self.assertIn(
                "rag_canary_fin_7391",
                " ".join(document["content"] for document in documents).lower(),
            )

    def test_none_policy_exposes_raw_retrieval_but_rag_policy_filters_it(self):
        case = next(
            case for case in load_dataset(DATASET) if case["case_id"] == "atk-045"
        )
        documents = retrieved_documents_for_case(case)
        none_context = DefenseContext(
            case=case,
            system_prompt=case["system_prompt"],
            user_prompt=case["prompt"],
            retrieved_documents=documents,
        )
        none_execution = PolicyEngine("none").before_model(none_context)
        self.assertIn("RAG_CANARY_FIN_7391", none_execution.user_prompt)
        self.assertIn('permission="denied"', none_execution.user_prompt)

        defended_context = DefenseContext(
            case=case,
            system_prompt=case["system_prompt"],
            user_prompt=case["prompt"],
            retrieved_documents=documents,
        )
        defended_execution = PolicyEngine("rag_defense").before_model(defended_context)
        self.assertNotIn("RAG_CANARY_FIN_7391", defended_execution.user_prompt)
        self.assertNotIn('permission="denied"', defended_execution.user_prompt)
        self.assertTrue(
            any(
                "unauthorized_document" in evidence
                for decision in defended_execution.decisions
                for evidence in decision.evidence
            )
        )


if __name__ == "__main__":
    unittest.main()
