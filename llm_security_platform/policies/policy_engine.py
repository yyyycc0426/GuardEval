from dataclasses import dataclass, field
from time import perf_counter
from uuid import uuid4

from llm_security_platform.app.schemas import DefenseDecision
from llm_security_platform.app.rag_context import render_untrusted_documents
from llm_security_platform.policies.base import DefenseContext
from llm_security_platform.policies.input_defense import HARDENED_SUFFIX


POLICY_ORDER = ("input_defense", "rag_defense", "output_defense")


def parse_policy_bundle(value):
    if not value or value == "none":
        return []
    if value == "baseline":
        return ["baseline"]
    parts = [part.strip() for part in value.replace("+", ",").split(",") if part.strip()]
    unsupported = set(parts) - set(POLICY_ORDER)
    if unsupported:
        raise ValueError(f"Unsupported defense policies: {', '.join(sorted(unsupported))}")
    return [name for name in POLICY_ORDER if name in parts]


@dataclass
class DefenseExecution:
    system_prompt: str
    user_prompt: str
    response_text: str = ""
    blocked: bool = False
    review_required: bool = False
    decisions: list[DefenseDecision] = field(default_factory=list)


class PolicyEngine:
    def __init__(self, bundle, versions=None, tenant_id="default"):
        self.bundle = parse_policy_bundle(bundle) if isinstance(bundle, str) else list(bundle)
        self.versions = versions or {}
        self.tenant_id = tenant_id
        
        self.policies = {}
        for name in self.bundle:
            if name == "baseline":
                continue
            version = self.versions.get(name) or f"{name.split('_')[0]}_v1"
            self.policies[name] = self._load_policy(name, version)

    def _load_policy(self, name, version):
        from llm_security_platform.app import db
        policy_record = db.get_defense_policy(name, version, tenant_id=self.tenant_id)
        config = policy_record["config"] if policy_record else {}
        
        if name == "input_defense":
            from llm_security_platform.policies.input_defense import InputDefense
            return InputDefense(version=version, config=config)
        elif name == "rag_defense":
            from llm_security_platform.policies.rag_defense import RAGDefense
            return RAGDefense(version=version, config=config)
        elif name == "output_defense":
            from llm_security_platform.policies.output_defense import OutputDefense
            return OutputDefense(version=version, config=config)
        else:
            raise ValueError(f"Unknown policy name: {name}")

    def _baseline(self, context):
        started = perf_counter()
        from llm_security_platform.app.detectors import detect_input_risk
        from llm_security_platform.app import db
        
        version = self.versions.get("baseline") or "baseline_v1"
        policy_record = db.get_defense_policy("baseline", version, tenant_id=self.tenant_id)
        config = policy_record["config"] if policy_record else {}
        
        threshold = config.get("block_threshold", 0.7)
        suffix = config.get("system_prompt_suffix", HARDENED_SUFFIX)

        score, signals = detect_input_risk(context.user_prompt)
        blocked = score >= threshold
        return DefenseDecision(
            policy_name="baseline",
            policy_version=version,
            enabled=True,
            action="block" if blocked else "rewrite",
            risk_level="high" if blocked else "medium",
            reason="Legacy rule baseline blocked high-risk input." if blocked else "Legacy system hardening applied.",
            evidence=signals or ["baseline_system_hardening"],
            before=context.user_prompt,
            after=None if blocked else context.user_prompt,
            latency_ms=round((perf_counter() - started) * 1000, 3),
            audit_id=f"def-{uuid4().hex}",
            metadata={"system_prompt_suffix": suffix, "risk_score": score},
        )

    def before_model(self, context: DefenseContext):
        execution = DefenseExecution(context.system_prompt, context.user_prompt)
        for name in self.bundle:
            if name == "output_defense":
                continue
            decision = self._baseline(context) if name == "baseline" else self.policies[name].apply(context)
            execution.decisions.append(decision)
            if decision.metadata.get("system_prompt_suffix"):
                execution.system_prompt += "\n\n" + decision.metadata["system_prompt_suffix"]
            if decision.after is not None:
                execution.user_prompt = decision.after
                context.user_prompt = decision.after
            if decision.action == "block":
                execution.blocked = True
                break
            if decision.action == "review":
                execution.review_required = True
        if (
            not execution.blocked
            and context.retrieved_documents
            and "rag_defense" not in self.bundle
        ):
            raw_context = render_untrusted_documents(context.retrieved_documents)
            execution.user_prompt = f"{execution.user_prompt}\n\n{raw_context}".strip()
            context.user_prompt = execution.user_prompt
        return execution

    def after_model(self, context: DefenseContext, execution: DefenseExecution):
        execution.response_text = context.response_text
        if "output_defense" not in self.bundle:
            return execution
        decision = self.policies["output_defense"].apply(context)
        execution.decisions.append(decision)
        if decision.after is not None:
            execution.response_text = decision.after
        if decision.action == "review" or decision.metadata.get("needs_review"):
            execution.review_required = True
            execution.decisions.append(
                DefenseDecision(
                    policy_name="human_review_router",
                    policy_version="review_router_v1",
                    enabled=True,
                    action="review",
                    risk_level=decision.risk_level,
                    reason="High-risk output transformation requires human confirmation.",
                    evidence=decision.evidence,
                    before=decision.before,
                    after=decision.after,
                    latency_ms=0.0,
                    audit_id=f"def-{uuid4().hex}",
                    metadata={"source_policy": decision.policy_name},
                )
            )
        return execution
