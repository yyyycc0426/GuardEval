from abc import ABC
from dataclasses import dataclass, field
from time import perf_counter
from uuid import uuid4

from llm_security_platform.app.schemas import DefenseDecision


@dataclass
class DefenseContext:
    case: dict
    system_prompt: str
    user_prompt: str
    retrieved_documents: list[dict] = field(default_factory=list)
    response_text: str = ""


class DefensePolicy(ABC):
    name = "base"
    version = "v1"

    @staticmethod
    def timer():
        return perf_counter()

    def decision(
        self,
        *,
        started_at,
        action,
        risk_level,
        reason,
        evidence,
        before=None,
        after=None,
        metadata=None,
    ):
        return DefenseDecision(
            policy_name=self.name,
            policy_version=self.version,
            enabled=True,
            action=action,
            risk_level=risk_level,
            reason=reason,
            evidence=evidence,
            before=before,
            after=after,
            latency_ms=round((perf_counter() - started_at) * 1000, 3),
            audit_id=f"def-{uuid4().hex}",
            metadata=metadata or {},
        )
