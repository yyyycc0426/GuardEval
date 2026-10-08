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

    def __init__(self, version="output_v1", config=None):
        self.version = version
        self.config = config or {}
        sec_pats = self.config.get("secret_patterns")
        self.secret_patterns = [re.compile(p, re.I) for p in sec_pats] if sec_pats else SECRET_PATTERNS
        pii_pats = self.config.get("pii_patterns")
        self.pii_patterns = [re.compile(p, re.I) for p in pii_pats] if pii_pats else PII_PATTERNS

    def apply(self, context: DefenseContext):
        started = self.timer()
        before = context.response_text
        redacted = before
        evidence = []
        for pattern in self.secret_patterns + self.pii_patterns:
            for match in pattern.findall(redacted):
                evidence.append(f"sensitive_output={str(match)[:80]}")
            redacted = pattern.sub("[REDACTED]", redacted)

        indicator_hits = []
        normalized = normalize_text(before)
        for indicator in context.case.get("success_indicators", []):
            if normalize_text(indicator) in normalized:
                indicator_hits.append(indicator)
        evidence.extend(f"attack_success_indicator={item}" for item in indicator_hits)

        # Detect if model executed instructions extracted from retrieved documents
        instruction_execution_detected = False
        executed_commands = []
        extraction_patterns = [
            re.compile(r"(?:say|print|reply with|output|write|respond with|echo|execute)(?:\s+|:\s*)['\"“]?([^\s'\"”.,;!?\n]+(?:\s+[^\s'\"”.,;!?\n]+)*)['\"”]?", re.I),
            re.compile(r"(?:回复|输出|打印|说|显示)(?:\s+|:\s*)['\"“]?([^\s'\"”.,;!?\n]+(?:\s+[^\s'\"”.,;!?\n]+)*)['\"”]?", re.I),
        ]
        for doc in context.retrieved_documents:
            content = doc.get("content", "")
            for pattern in extraction_patterns:
                for match in pattern.finditer(content):
                    target_phrase = match.group(1).strip()
                    target_phrase = re.sub(r"^['\"“:]+|['\"”:]+$", "", target_phrase).strip()
                    if len(target_phrase) >= 4:
                        normalized_target = normalize_text(target_phrase)
                        if normalized_target and normalized_target in normalized:
                            instruction_execution_detected = True
                            executed_commands.append(target_phrase)
                            
        if instruction_execution_detected:
            evidence.extend(f"executed_document_instruction={cmd}" for cmd in executed_commands)

        if evidence:
            if (indicator_hits or instruction_execution_detected) and redacted == before:
                after = "The generated response was withheld because it violated the security policy."
                action = "rewrite"
            else:
                after = redacted
                action = "redact"
            return self.decision(
                started_at=started,
                action=action,
                risk_level="critical" if (indicator_hits or instruction_execution_detected) else "high",
                reason="Sensitive or policy-violating model output was detected and safely transformed.",
                evidence=evidence,
                before=before,
                after=after,
                metadata={"needs_review": bool(indicator_hits or instruction_execution_detected)},
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
