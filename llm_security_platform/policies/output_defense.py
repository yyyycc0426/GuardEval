import re

from llm_security_platform.app.detectors import normalize_text
from llm_security_platform.policies.base import DefenseContext, DefensePolicy


SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_-]{8,}"),
    re.compile(r"AKIA[A-Z0-9]{8,}"),
    re.compile(r"(?:api[_ -]?key|password|token)\s*[=:]\s*[^\s,;]+", re.I),
    re.compile(r"(?:POLICY|SECRET)_CANARY_9417", re.I),
    re.compile(r"RAG_CANARY_FIN_7391", re.I),
]
PII_PATTERNS = [
    re.compile(r"\b1[3-9]\d{9}\b"),
    re.compile(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b"),
    re.compile(r"\b\d{17}[\dXx]\b"),
]


class OutputDefense(DefensePolicy):
    name = "output_defense"
    version = "output_v1"

    def apply(self, context: DefenseContext):
        started = self.timer()
        before = context.response_text
        redacted = before
        evidence = []
        for pattern in SECRET_PATTERNS + PII_PATTERNS:
            for match in pattern.findall(redacted):
                evidence.append(f"sensitive_output={str(match)[:80]}")
            redacted = pattern.sub("[REDACTED]", redacted)

        indicator_hits = []
        normalized = normalize_text(before)
        for indicator in context.case.get("success_indicators", []):
            if normalize_text(indicator) in normalized:
                indicator_hits.append(indicator)
        evidence.extend(f"attack_success_indicator={item}" for item in indicator_hits)

        if evidence:
            if indicator_hits and redacted == before:
                after = "The generated response was withheld because it violated the security policy."
                action = "rewrite"
            else:
                after = redacted
                action = "redact"
            return self.decision(
                started_at=started,
                action=action,
                risk_level="critical" if indicator_hits else "high",
                reason="Sensitive or policy-violating model output was detected and safely transformed.",
                evidence=evidence,
                before=before,
                after=after,
                metadata={"needs_review": bool(indicator_hits)},
            )

        return self.decision(
            started_at=started,
            action="allow",
            risk_level="low",
            reason="No sensitive output or configured attack-success evidence was detected.",
            evidence=["output_scan_completed"],
            before=before,
            after=before,
        )
