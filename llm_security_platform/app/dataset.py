import json
from collections import Counter
from pathlib import Path

from llm_security_platform.app.detectors import normalize_text


REQUIRED_METADATA_FIELDS = {
    "risk_type",
    "attack_method",
    "language",
    "severity",
    "expected_behavior",
    "human_label",
    "dataset_version",
}


def load_dataset(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def validate_dataset(cases, minimum_cases=60, minimum_benign_ratio=0.25):
    errors = []
    case_ids = [case.get("case_id") for case in cases]
    duplicates = [case_id for case_id, count in Counter(case_ids).items() if count > 1]
    if len(cases) < minimum_cases:
        errors.append(f"dataset has {len(cases)} cases; expected at least {minimum_cases}")
    if duplicates:
        errors.append(f"duplicate case ids: {', '.join(sorted(duplicates))}")

    benign_count = sum(case.get("risk_type") == "benign" for case in cases)
    benign_ratio = benign_count / len(cases) if cases else 0
    if benign_ratio < minimum_benign_ratio:
        errors.append(
            f"benign ratio is {benign_ratio:.2%}; expected at least {minimum_benign_ratio:.0%}"
        )

    for case in cases:
        metadata = case.get("metadata", {})
        missing = REQUIRED_METADATA_FIELDS - metadata.keys()
        if missing:
            errors.append(f"{case.get('case_id', '<missing>')} missing metadata: {sorted(missing)}")
        if metadata.get("risk_type") != case.get("risk_type"):
            errors.append(f"{case.get('case_id', '<missing>')} has inconsistent risk_type")
        if metadata.get("human_label") is not True:
            errors.append(f"{case.get('case_id', '<missing>')} is not label-checked")
        if (
            metadata.get("dataset_version") == "attackset_v3"
            and case.get("risk_type") == "rag_data_leakage"
        ):
            documents = metadata.get("retrieved_documents")
            if not isinstance(documents, list) or not documents:
                errors.append(
                    f"{case.get('case_id', '<missing>')} missing retrieved_documents"
                )
                continue
            indicators = [
                normalize_text(item) for item in case.get("success_indicators", []) if item
            ]
            prompt = normalize_text(case.get("prompt", ""))
            if any(indicator in prompt for indicator in indicators):
                errors.append(
                    f"{case.get('case_id', '<missing>')} exposes a success indicator in prompt"
                )
            document_text = normalize_text(
                " ".join(str(document.get("content", "")) for document in documents)
            )
            if indicators and not any(indicator in document_text for indicator in indicators):
                errors.append(
                    f"{case.get('case_id', '<missing>')} has no success indicator in retrieved documents"
                )
            for document in documents:
                missing_document_fields = {
                    "source", "permission", "content"
                } - document.keys()
                if missing_document_fields:
                    errors.append(
                        f"{case.get('case_id', '<missing>')} document missing fields: "
                        f"{sorted(missing_document_fields)}"
                    )
    return errors
